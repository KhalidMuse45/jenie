"""Approving and rejecting delegation plans.

This is the moment a proposal becomes real work, and it is the one place in
Jenie where getting the ordering wrong has consequences that are hard to see.
Approving a plan must create exactly the tasks it proposed, tell exactly the
people it named, and leave a record of who decided what -- all of it or none of
it.

The sequence follows the specification:

    1. lock the plan
    2. verify it is awaiting approval
    3. verify the expected version
    4. verify the actor may decide
    5. record the decision
    6. create the work items
    7. record their creation and assignment
    8. record an audit entry
    9. queue notifications
   10. mark the plan decided

Nothing is sent while the transaction is open. Step 9 writes rows; a worker
delivers them after the commit. Sending inside the transaction would mean a
failure partway through leaves people told about work that then rolls back.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Approval,
    AuditEvent,
    DelegationPlan,
    DelegationPlanItem,
    Membership,
    OutboundMessage,
    User,
    WorkItem,
)
from app.domain.delegation.service import InvalidPlanState, list_items
from app.domain.enums import (
    ApprovalDecision,
    AuditAction,
    DelegationPlanStatus,
    OutboundMessageType,
    WorkItemType,
)
from app.domain.notifications import (
    enqueue,
    render_assignment,
    render_plan_approved,
    render_plan_rejected,
)
from app.domain.permissions import Action, Actor, require, subject_for_plan
from app.domain.work import create_work_item


class PlanNotFound(LookupError):
    """No plan with that identifier."""


class PlanChanged(ValueError):
    """The plan moved on between being read and being decided.

    Raised when the caller names a version that is no longer current. The
    message is written for a person: they are being asked to look again, not
    told about a conflict.
    """


@dataclass(frozen=True, slots=True)
class Outcome:
    plan: DelegationPlan
    approval: Approval
    created_work_items: list[WorkItem]
    notifications: list[OutboundMessage]
    #: True when the plan already carried this decision and nothing new happened.
    already_decided: bool = False


async def approve_plan(
    session: AsyncSession,
    plan_id: uuid.UUID,
    *,
    actor: Actor,
    expected_version: int | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> Outcome:
    """Turn a proposal into assigned work, in one transaction."""
    now = now or datetime.now(UTC)

    plan = await _lock(session, plan_id)

    # Approving twice is something a person can easily do -- a second text, a
    # retried webhook. The second one must not create a second set of tasks.
    if plan.status is DelegationPlanStatus.APPROVED:
        return Outcome(
            plan=plan,
            approval=await _existing_decision(session, plan, ApprovalDecision.APPROVED),
            created_work_items=[],
            notifications=[],
            already_decided=True,
        )

    _require_pending(plan)
    _require_version(plan, expected_version)
    require(actor, Action.APPROVE_PLAN, subject_for_plan(plan))

    before = _snapshot(plan)
    items = await list_items(session, plan)
    scope = await session.get(WorkItem, plan.scope_work_item_id)
    initiative = await session.get(WorkItem, scope.parent_id) if scope.parent_id else None

    approval = Approval(
        plan_id=plan.id,
        plan_version=plan.version,
        approver_membership_id=actor.membership_id,
        decision=ApprovalDecision.APPROVED,
        comment=comment,
        decided_at=now,
    )
    session.add(approval)
    await session.flush()

    created = await _materialise(session, plan, items, scope, actor)

    delegated_by = await _display_name(session, plan.created_by_membership_id)
    approved_by = await _display_name(session, actor.membership_id)

    notifications = [
        await enqueue(
            session,
            organization_id=plan.organization_id,
            recipient_membership_id=work_item.owner_membership_id,
            message_type=OutboundMessageType.ASSIGNMENT,
            body=render_assignment(
                initiative_title=initiative.title if initiative else scope.title,
                responsibility_title=scope.title,
                task_title=work_item.title,
                short_code=work_item.short_code,
                due_at=work_item.due_at,
                timezone=await _timezone(session, plan.organization_id),
                delegated_by=delegated_by,
                approved_by=approved_by,
            ),
            now=now,
        )
        for work_item in created
    ]

    # Telling someone they approved their own plan is noise. At the top of the
    # organization the creator and the approver are the same person.
    if plan.created_by_membership_id != actor.membership_id:
        notifications.append(
            await enqueue(
                session,
                organization_id=plan.organization_id,
                recipient_membership_id=plan.created_by_membership_id,
                message_type=OutboundMessageType.PLAN_APPROVED,
                body=render_plan_approved(
                    plan_code=plan.short_code,
                    responsibility_title=scope.title,
                    approved_by=approved_by,
                    task_count=len(created),
                ),
                now=now,
            )
        )

    plan.status = DelegationPlanStatus.APPROVED
    plan.approved_at = now
    plan.version += 1

    session.add(
        AuditEvent(
            organization_id=plan.organization_id,
            actor_membership_id=actor.membership_id,
            action=AuditAction.APPROVE_PLAN,
            target_type="delegation_plan",
            target_id=plan.id,
            before_state=before,
            after_state=_snapshot(plan),
            payload={
                "created_work_item_ids": [str(item.id) for item in created],
                "notified": len(notifications),
            },
            created_at=now,
        )
    )
    await session.flush()

    return Outcome(
        plan=plan,
        approval=approval,
        created_work_items=created,
        notifications=notifications,
    )


async def reject_plan(
    session: AsyncSession,
    plan_id: uuid.UUID,
    *,
    actor: Actor,
    expected_version: int | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> Outcome:
    """Decline a proposal. Creates no work."""
    now = now or datetime.now(UTC)

    plan = await _lock(session, plan_id)

    if plan.status is DelegationPlanStatus.REJECTED:
        return Outcome(
            plan=plan,
            approval=await _existing_decision(session, plan, ApprovalDecision.REJECTED),
            created_work_items=[],
            notifications=[],
            already_decided=True,
        )

    _require_pending(plan)
    _require_version(plan, expected_version)
    require(actor, Action.REJECT_PLAN, subject_for_plan(plan))

    before = _snapshot(plan)
    scope = await session.get(WorkItem, plan.scope_work_item_id)

    approval = Approval(
        plan_id=plan.id,
        plan_version=plan.version,
        approver_membership_id=actor.membership_id,
        decision=ApprovalDecision.REJECTED,
        comment=comment,
        decided_at=now,
    )
    session.add(approval)

    notifications = []
    if plan.created_by_membership_id != actor.membership_id:
        notifications.append(
            await enqueue(
                session,
                organization_id=plan.organization_id,
                recipient_membership_id=plan.created_by_membership_id,
                message_type=OutboundMessageType.PLAN_REJECTED,
                body=render_plan_rejected(
                    plan_code=plan.short_code,
                    responsibility_title=scope.title,
                    rejected_by=await _display_name(session, actor.membership_id),
                    comment=comment,
                ),
                now=now,
            )
        )

    plan.status = DelegationPlanStatus.REJECTED
    plan.version += 1

    session.add(
        AuditEvent(
            organization_id=plan.organization_id,
            actor_membership_id=actor.membership_id,
            action=AuditAction.REJECT_PLAN,
            target_type="delegation_plan",
            target_id=plan.id,
            before_state=before,
            after_state=_snapshot(plan),
            payload={"comment": comment},
            created_at=now,
        )
    )
    await session.flush()

    return Outcome(plan=plan, approval=approval, created_work_items=[], notifications=notifications)


async def _materialise(
    session: AsyncSession,
    plan: DelegationPlan,
    items: list[DelegationPlanItem],
    scope: WorkItem,
    actor: Actor,
) -> list[WorkItem]:
    """Create one work item per plan item, preserving any nesting.

    Items are flat today, so every parent resolves to the plan's scope. The map
    is kept because the schema allows a plan item to hang off another; if one
    does, ``create_work_item`` refuses it with a structural error rather than
    quietly flattening the shape somebody asked for.
    """
    created: list[WorkItem] = []
    by_plan_item: dict[uuid.UUID, WorkItem] = {}

    for item in items:
        parent = by_plan_item.get(item.parent_plan_item_id, scope)

        work_item = await create_work_item(
            session,
            organization_id=plan.organization_id,
            item_type=item.type or WorkItemType.TASK,
            title=item.title,
            description=item.description,
            created_by_membership_id=plan.created_by_membership_id,
            parent=parent,
            owner_membership_id=item.proposed_assignee_membership_id,
            due_at=item.proposed_due_at,
        )
        created.append(work_item)
        by_plan_item[item.id] = work_item

    return created


async def _lock(session: AsyncSession, plan_id: uuid.UUID) -> DelegationPlan:
    """Read the plan under a row lock and hold it for the rest of the transaction.

    Everything after this -- the status check especially -- is only meaningful
    while nobody else can move the row underneath us.

    Deliberately an explicit SELECT ... FOR UPDATE rather than
    ``session.get(..., with_for_update=True)``. ``get()`` serves an object that
    is already in the session's identity map without going to the database at
    all, so the lock would silently do nothing in the most ordinary case: a
    caller that loaded the plan to show it to someone, then approves it in the
    same session.

    ``populate_existing`` matters for the same reason -- it overwrites the
    in-memory copy with what the row actually says now, so the status and
    version checked below are the committed ones and not a stale read.
    """
    plan = await session.scalar(
        select(DelegationPlan)
        .where(DelegationPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise PlanNotFound(f"no delegation plan {plan_id}")
    return plan


def _require_pending(plan: DelegationPlan) -> None:
    if plan.status is DelegationPlanStatus.DRAFT:
        raise InvalidPlanState(f"Plan {plan.short_code} hasn't been sent for approval yet.")
    if plan.status is not DelegationPlanStatus.PENDING_APPROVAL:
        raise InvalidPlanState(f"Plan {plan.short_code} has already been decided.")


def _require_version(plan: DelegationPlan, expected_version: int | None) -> None:
    if expected_version is not None and plan.version != expected_version:
        raise PlanChanged(
            f"Plan {plan.short_code} changed after I showed it to you. "
            "Have another look before deciding."
        )


def _snapshot(plan: DelegationPlan) -> dict[str, object]:
    return {"status": plan.status.value, "version": plan.version}


async def _existing_decision(
    session: AsyncSession, plan: DelegationPlan, decision: ApprovalDecision
) -> Approval:
    return await session.scalar(
        select(Approval)
        .where(Approval.plan_id == plan.id, Approval.decision == decision)
        .order_by(Approval.decided_at.desc())
        .limit(1)
    )


async def _display_name(session: AsyncSession, membership_id: uuid.UUID) -> str:
    name = await session.scalar(
        select(User.display_name)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.id == membership_id)
    )
    return name or "someone"


async def _timezone(session: AsyncSession, organization_id: uuid.UUID) -> str:
    from app.database.models import Organization

    return await session.scalar(
        select(Organization.timezone).where(Organization.id == organization_id)
    )

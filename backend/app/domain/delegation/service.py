"""Building and submitting delegation plans.

Everything here operates on proposals. No WorkItem is created, no assignee is
notified, and nobody's task list changes -- that happens only on approval.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    DelegationPlan,
    DelegationPlanItem,
    Membership,
    User,
    WorkItem,
)
from app.domain.codes import generate_plan_code
from app.domain.delegation.states import EDITABLE_STATUSES
from app.domain.enums import (
    DelegationPlanStatus,
    OutboundMessageType,
    WorkItemStatus,
    WorkItemType,
)
from app.domain.notifications import enqueue, render_plan_submitted
from app.domain.organizations.graph import OrgGraph

_CODE_ATTEMPTS = 10


class PlanNotEditable(ValueError):
    """The plan has been decided and no longer accepts changes."""


class PlanNotReady(ValueError):
    """The plan cannot be submitted as it stands."""


class InvalidPlanState(ValueError):
    """The requested move is not legal from the plan's current state."""


async def create_plan(
    session: AsyncSession,
    *,
    scope: WorkItem,
    created_by_membership_id: uuid.UUID,
) -> DelegationPlan:
    """Start a draft plan for one responsibility."""
    if scope.type is not WorkItemType.RESPONSIBILITY:
        raise PlanNotReady(
            "A delegation plan breaks down a responsibility, "
            f"and '{scope.title}' is a {scope.type.value.lower()}."
        )
    if scope.status is WorkItemStatus.CANCELLED:
        raise PlanNotReady(f"'{scope.title}' was cancelled, so there is nothing to plan for.")

    plan = DelegationPlan(
        organization_id=scope.organization_id,
        scope_work_item_id=scope.id,
        created_by_membership_id=created_by_membership_id,
        status=DelegationPlanStatus.DRAFT,
        short_code=await _allocate_code(session, scope.organization_id),
        version=1,
    )
    session.add(plan)
    await session.flush()
    return plan


async def add_item(
    session: AsyncSession,
    plan: DelegationPlan,
    *,
    title: str,
    proposed_assignee_membership_id: uuid.UUID | None = None,
    proposed_due_at: datetime | None = None,
    description: str | None = None,
    parent_plan_item_id: uuid.UUID | None = None,
) -> DelegationPlanItem:
    """Add a proposed piece of work to a plan."""
    _require_editable(plan)

    item = DelegationPlanItem(
        plan_id=plan.id,
        organization_id=plan.organization_id,
        parent_plan_item_id=parent_plan_item_id,
        type=WorkItemType.TASK,
        title=title.strip(),
        description=description,
        proposed_assignee_membership_id=proposed_assignee_membership_id,
        proposed_due_at=proposed_due_at,
        sort_order=await _next_sort_order(session, plan),
    )
    session.add(item)
    _touch(plan)
    await session.flush()
    return item


_UNSET = object()


async def update_item(
    session: AsyncSession,
    plan: DelegationPlan,
    item: DelegationPlanItem,
    *,
    title: str | None = None,
    proposed_assignee_membership_id: uuid.UUID | None | object = _UNSET,
    proposed_due_at: datetime | None | object = _UNSET,
    description: str | None | object = _UNSET,
) -> DelegationPlanItem:
    """Change one proposed item.

    A sentinel rather than ``None`` for the optional fields, so that clearing an
    assignee and leaving it alone are different requests.
    """
    _require_editable(plan)
    _require_membership(plan, item)

    if title is not None:
        item.title = title.strip()
    if proposed_assignee_membership_id is not _UNSET:
        item.proposed_assignee_membership_id = proposed_assignee_membership_id  # type: ignore[assignment]
    if proposed_due_at is not _UNSET:
        item.proposed_due_at = proposed_due_at  # type: ignore[assignment]
    if description is not _UNSET:
        item.description = description  # type: ignore[assignment]

    _touch(plan)
    await session.flush()
    return item


async def remove_item(
    session: AsyncSession, plan: DelegationPlan, item: DelegationPlanItem
) -> None:
    _require_editable(plan)
    _require_membership(plan, item)

    await session.delete(item)
    _touch(plan)
    await session.flush()


async def submit_plan(
    session: AsyncSession,
    plan: DelegationPlan,
    *,
    now: datetime | None = None,
) -> DelegationPlan:
    """Send a draft to its approver.

    Validation lives here rather than at approval time so the person who wrote
    the plan is the one who hears about its problems.

    Who may call this is the permission engine's decision; this function is
    concerned only with whether the plan itself is fit to send.
    """
    if plan.status is not DelegationPlanStatus.DRAFT:
        raise InvalidPlanState(_describe_state(plan))

    now = now or datetime.now(UTC)
    await _validate_ready(session, plan, now)

    plan.required_approver_membership_id = await _approver_for(session, plan)
    plan.status = DelegationPlanStatus.PENDING_APPROVAL
    plan.submitted_at = now
    plan.version += 1
    await session.flush()

    await _notify_approver(session, plan, now)
    return plan


async def _notify_approver(session: AsyncSession, plan: DelegationPlan, now: datetime) -> None:
    """Tell the approver a plan is waiting.

    Queued in the same transaction as the submission, like every other
    notification Jenie sends.
    """
    if plan.required_approver_membership_id == plan.created_by_membership_id:
        return

    scope = await session.get(WorkItem, plan.scope_work_item_id)
    submitted_by = await session.scalar(
        select(User.display_name)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.id == plan.created_by_membership_id)
    )

    await enqueue(
        session,
        organization_id=plan.organization_id,
        recipient_membership_id=plan.required_approver_membership_id,
        message_type=OutboundMessageType.PLAN_SUBMITTED,
        body=render_plan_submitted(
            plan_code=plan.short_code,
            responsibility_title=scope.title,
            submitted_by=submitted_by or "Someone",
            task_count=len(await list_items(session, plan)),
        ),
        now=now,
    )


async def list_items(session: AsyncSession, plan: DelegationPlan) -> list[DelegationPlanItem]:
    """The plan's items, in order.

    Read through a query rather than the ``items`` relationship. Items are
    written as rows rather than appended to the collection, so on a plan that is
    already persistent the relationship would issue a lazy load -- which under
    asyncio raises rather than quietly working.
    """
    return list(
        await session.scalars(
            select(DelegationPlanItem)
            .where(DelegationPlanItem.plan_id == plan.id)
            .order_by(DelegationPlanItem.sort_order)
        )
    )


async def _validate_ready(session: AsyncSession, plan: DelegationPlan, now: datetime) -> None:
    items = await list_items(session, plan)

    if not items:
        raise PlanNotReady("The plan is empty. Add at least one task before sending it.")

    nameless = [item.title for item in items if item.proposed_assignee_membership_id is None]
    if nameless:
        raise PlanNotReady(f"Nobody is proposed for: {', '.join(nameless)}.")

    undated = [item.title for item in items if item.proposed_due_at is None]
    if undated:
        raise PlanNotReady(f"No due date for: {', '.join(undated)}.")

    overdue = [item.title for item in items if item.proposed_due_at < now]
    if overdue:
        raise PlanNotReady(f"These are already past due: {', '.join(overdue)}.")

    # You may only propose work for yourself and the people beneath you.
    # Approval would otherwise be a way to assign work sideways or upward.
    reachable = await OrgGraph(session).scope_ids(plan.created_by_membership_id)
    unreachable = [
        item.title for item in items if item.proposed_assignee_membership_id not in reachable
    ]
    if unreachable:
        raise PlanNotReady(
            "You can only propose work for yourself and the people who report to you. "
            f"Check: {', '.join(unreachable)}."
        )


async def _approver_for(session: AsyncSession, plan: DelegationPlan) -> uuid.UUID:
    """Who has to say yes.

    The creator's manager. When the creator has no manager -- they are the top
    of the organization -- they approve their own plan. That is a formality
    rather than an escalation, since a superadmin can already do anything
    directly, and it keeps one code path and one audit record.
    """
    chain = await OrgGraph(session).ancestors(plan.created_by_membership_id)
    if chain:
        return chain[0].membership_id
    return plan.created_by_membership_id


def _require_editable(plan: DelegationPlan) -> None:
    if plan.status not in EDITABLE_STATUSES:
        raise PlanNotEditable(_describe_state(plan))


def _require_membership(plan: DelegationPlan, item: DelegationPlanItem) -> None:
    if item.plan_id != plan.id:
        raise PlanNotEditable("That item belongs to a different plan.")


def _describe_state(plan: DelegationPlan) -> str:
    if plan.status is DelegationPlanStatus.APPROVED:
        return f"Plan {plan.short_code} was already approved and can't be changed."
    if plan.status is DelegationPlanStatus.REJECTED:
        return f"Plan {plan.short_code} was rejected. Start a new one instead."
    if plan.status is DelegationPlanStatus.PENDING_APPROVAL:
        return f"Plan {plan.short_code} has already been sent for approval."
    return f"Plan {plan.short_code} is a draft."


def _touch(plan: DelegationPlan) -> None:
    """Every change to a plan's contents moves its version.

    An approval names the version it approved, so an edit between "here is the
    plan" and "approve" cannot be mistaken for agreement to the new text.
    """
    plan.version += 1


async def _next_sort_order(session: AsyncSession, plan: DelegationPlan) -> int:
    highest = await session.scalar(
        select(DelegationPlanItem.sort_order)
        .where(DelegationPlanItem.plan_id == plan.id)
        .order_by(DelegationPlanItem.sort_order.desc())
        .limit(1)
    )
    return 0 if highest is None else highest + 1


async def _allocate_code(session: AsyncSession, organization_id: uuid.UUID) -> str:
    for _ in range(_CODE_ATTEMPTS):
        candidate = generate_plan_code()
        taken = await session.scalar(
            select(DelegationPlan.id).where(
                DelegationPlan.organization_id == organization_id,
                DelegationPlan.short_code == candidate,
            )
        )
        if taken is None:
            return candidate

    raise RuntimeError("could not allocate a unique short code")

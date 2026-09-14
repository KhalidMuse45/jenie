"""Drafting, sending, and deciding delegation plans."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import ActorDep, SessionDep
from app.api.envelope import ok
from app.api.schemas import (
    AddPlanItemIn,
    CreatePlanIn,
    DecideIn,
    DecisionOut,
    PlanItemOut,
    PlanOut,
    UpdatePlanItemIn,
    WorkItemOut,
)
from app.database.models import DelegationPlan, DelegationPlanItem, WorkItem
from app.domain.delegation import (
    add_item,
    approve_plan,
    create_plan,
    reject_plan,
    remove_item,
    submit_plan,
    update_item,
)
from app.domain.delegation.service import list_items
from app.domain.permissions import (
    Action,
    Actor,
    require,
    subject_for_plan,
    subject_for_work_item,
)

router = APIRouter(tags=["delegation"])


async def _load_plan(session: SessionDep, actor: Actor, plan_id: uuid.UUID) -> DelegationPlan:
    plan = await session.get(DelegationPlan, plan_id)
    if plan is None or plan.organization_id != actor.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such plan.")
    return plan


async def _dump_plan(session: SessionDep, plan: DelegationPlan) -> dict[str, Any]:
    """Build the response without touching ``plan.items``.

    Validating straight off the ORM row would read the relationship, and on a
    persistent plan that is a lazy load -- which under asyncio raises rather
    than quietly working. Items always come from an explicit query.
    """
    return PlanOut(
        id=plan.id,
        short_code=plan.short_code,
        status=plan.status,
        scope_work_item_id=plan.scope_work_item_id,
        created_by_membership_id=plan.created_by_membership_id,
        required_approver_membership_id=plan.required_approver_membership_id,
        version=plan.version,
        submitted_at=plan.submitted_at,
        approved_at=plan.approved_at,
        items=[PlanItemOut.model_validate(item) for item in await list_items(session, plan)],
    ).model_dump(mode="json")


@router.post("/delegation-plans", status_code=status.HTTP_201_CREATED)
async def create(body: CreatePlanIn, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    scope = await session.get(WorkItem, body.scope_work_item_id)
    if scope is None or scope.organization_id != actor.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such work item.")

    require(actor, Action.CREATE_PLAN, subject_for_work_item(scope))

    plan = await create_plan(session, scope=scope, created_by_membership_id=actor.membership_id)
    await session.commit()
    return ok(await _dump_plan(session, plan))


@router.get("/delegation-plans/{plan_id}")
async def read(plan_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    plan = await _load_plan(session, actor, plan_id)

    scope = await session.get(WorkItem, plan.scope_work_item_id)
    require(actor, Action.VIEW_WORK_ITEM, subject_for_work_item(scope))

    return ok(await _dump_plan(session, plan))


@router.get("/delegation-plans")
async def list_pending(session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    """Plans waiting on this actor.

    The answer to "what do I need to approve?", computed from the database.
    """
    plans = await session.scalars(
        select(DelegationPlan)
        .where(
            DelegationPlan.organization_id == actor.organization_id,
            DelegationPlan.required_approver_membership_id == actor.membership_id,
            DelegationPlan.status == "PENDING_APPROVAL",
        )
        .order_by(DelegationPlan.submitted_at)
    )
    return ok([await _dump_plan(session, plan) for plan in plans])


@router.post("/delegation-plans/{plan_id}/items", status_code=status.HTTP_201_CREATED)
async def add(
    plan_id: uuid.UUID, body: AddPlanItemIn, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    plan = await _load_plan(session, actor, plan_id)
    require(actor, Action.EDIT_PLAN, subject_for_plan(plan))

    await add_item(
        session,
        plan,
        title=body.title,
        description=body.description,
        proposed_assignee_membership_id=body.proposed_assignee_membership_id,
        proposed_due_at=body.proposed_due_at,
    )
    await session.commit()
    return ok(await _dump_plan(session, plan))


@router.patch("/delegation-plans/{plan_id}/items/{item_id}")
async def change(
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    body: UpdatePlanItemIn,
    session: SessionDep,
    actor: ActorDep,
) -> dict[str, Any]:
    plan = await _load_plan(session, actor, plan_id)
    require(actor, Action.EDIT_PLAN, subject_for_plan(plan))

    item = await session.get(DelegationPlanItem, item_id)
    if item is None or item.plan_id != plan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such plan item.")

    # Only the keys actually sent are forwarded, so omitting a field and sending
    # it as null stay different requests.
    supplied = {
        field: getattr(body, field)
        for field in body.model_fields_set
        if field != "title" or body.title is not None
    }
    await update_item(session, plan, item, **supplied)
    await session.commit()
    return ok(await _dump_plan(session, plan))


@router.delete("/delegation-plans/{plan_id}/items/{item_id}")
async def remove(
    plan_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    plan = await _load_plan(session, actor, plan_id)
    require(actor, Action.EDIT_PLAN, subject_for_plan(plan))

    item = await session.get(DelegationPlanItem, item_id)
    if item is None or item.plan_id != plan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such plan item.")

    await remove_item(session, plan, item)
    await session.commit()
    return ok(await _dump_plan(session, plan))


@router.post("/delegation-plans/{plan_id}/submit")
async def submit(plan_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    plan = await _load_plan(session, actor, plan_id)
    require(actor, Action.SUBMIT_PLAN, subject_for_plan(plan))

    await submit_plan(session, plan)
    await session.commit()
    return ok(await _dump_plan(session, plan))


@router.post("/delegation-plans/{plan_id}/approve")
async def approve(
    plan_id: uuid.UUID, body: DecideIn, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    """Authorization happens inside the transaction, not here.

    ``approve_plan`` takes the row lock first and checks permission under it, so
    a route that checked beforehand would only be duplicating a decision that
    has to be made at a specific moment anyway.
    """
    await _load_plan(session, actor, plan_id)

    outcome = await approve_plan(
        session,
        plan_id,
        actor=actor,
        expected_version=body.expected_version,
        comment=body.comment,
    )
    await session.commit()
    return ok(await _dump_outcome(session, outcome))


@router.post("/delegation-plans/{plan_id}/reject")
async def reject(
    plan_id: uuid.UUID, body: DecideIn, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    await _load_plan(session, actor, plan_id)

    outcome = await reject_plan(
        session,
        plan_id,
        actor=actor,
        expected_version=body.expected_version,
        comment=body.comment,
    )
    await session.commit()
    return ok(await _dump_outcome(session, outcome))


async def _dump_outcome(session: SessionDep, outcome) -> dict[str, Any]:
    plan = PlanOut(
        id=outcome.plan.id,
        short_code=outcome.plan.short_code,
        status=outcome.plan.status,
        scope_work_item_id=outcome.plan.scope_work_item_id,
        created_by_membership_id=outcome.plan.created_by_membership_id,
        required_approver_membership_id=outcome.plan.required_approver_membership_id,
        version=outcome.plan.version,
        submitted_at=outcome.plan.submitted_at,
        approved_at=outcome.plan.approved_at,
    )
    return DecisionOut(
        plan=plan,
        created_work_items=[
            WorkItemOut.model_validate(item) for item in outcome.created_work_items
        ],
        notified=len(outcome.notifications),
        already_decided=outcome.already_decided,
    ).model_dump(mode="json")

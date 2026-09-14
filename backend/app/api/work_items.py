"""Creating and moving work."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ActorDep, SessionDep
from app.api.envelope import ok
from app.api.schemas import CreateWorkItemIn, TreeNodeOut, WorkItemOut
from app.database.models import WorkItem
from app.domain.enums import WorkItemType
from app.domain.permissions import (
    Action,
    Actor,
    require,
    subject_for_work_item,
)
from app.domain.work import (
    cancel_work_item,
    complete_task,
    create_work_item,
    start_task,
    subtree,
)

router = APIRouter(tags=["work"])


async def _visible(session: SessionDep, actor: Actor, work_item_id: uuid.UUID) -> WorkItem:
    """Load a work item the actor is allowed to see.

    A work item in another organization reads as missing rather than forbidden:
    confirming it exists would leak the shape of somebody else's organization.
    """
    work_item = await session.get(WorkItem, work_item_id)
    if work_item is None or work_item.organization_id != actor.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such work item.")

    require(actor, Action.VIEW_WORK_ITEM, subject_for_work_item(work_item))
    return work_item


def _dump(work_item: WorkItem) -> dict[str, Any]:
    return WorkItemOut.model_validate(work_item).model_dump(mode="json")


@router.post("/work-items", status_code=status.HTTP_201_CREATED)
async def create(body: CreateWorkItemIn, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    parent = None

    if body.type is WorkItemType.INITIATIVE:
        require(actor, Action.CREATE_INITIATIVE)
    else:
        if body.parent_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"A {body.type.value.lower()} needs a parent.",
            )
        parent = await _visible(session, actor, body.parent_id)
        require(actor, Action.CREATE_WORK_ITEM, subject_for_work_item(parent))

    work_item = await create_work_item(
        session,
        organization_id=actor.organization_id,
        item_type=body.type,
        title=body.title,
        description=body.description,
        created_by_membership_id=actor.membership_id,
        parent=parent,
        owner_membership_id=body.owner_membership_id,
        due_at=body.due_at,
    )
    await session.commit()
    return ok(_dump(work_item))


@router.get("/work-items/{work_item_id}")
async def read(work_item_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    return ok(_dump(await _visible(session, actor, work_item_id)))


@router.get("/work-items/{work_item_id}/tree")
async def read_tree(
    work_item_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    root = await _visible(session, actor, work_item_id)

    nodes = await subtree(session, root.id)
    return ok(
        [
            TreeNodeOut(depth=node.depth, item=WorkItemOut.model_validate(node.item)).model_dump(
                mode="json"
            )
            for node in nodes
        ]
    )


@router.post("/work-items/{work_item_id}/start")
async def start(work_item_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    work_item = await _visible(session, actor, work_item_id)
    require(actor, Action.START_TASK, subject_for_work_item(work_item))

    result = await start_task(session, work_item, actor_membership_id=actor.membership_id)
    await session.commit()
    return ok({"work_item": _dump(work_item), "changed": result.changed})


@router.post("/work-items/{work_item_id}/complete")
async def complete(work_item_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    work_item = await _visible(session, actor, work_item_id)
    require(actor, Action.COMPLETE_TASK, subject_for_work_item(work_item))

    result = await complete_task(session, work_item, actor_membership_id=actor.membership_id)
    await session.commit()
    return ok({"work_item": _dump(work_item), "changed": result.changed})


@router.post("/work-items/{work_item_id}/cancel")
async def cancel(work_item_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    work_item = await _visible(session, actor, work_item_id)
    require(actor, Action.CANCEL_WORK_ITEM, subject_for_work_item(work_item))

    result = await cancel_work_item(session, work_item, actor_membership_id=actor.membership_id)
    await session.commit()
    return ok({"work_item": _dump(work_item), "changed": result.changed})

"""Creating work items.

The tree is strictly nested -- initiative, then responsibility, then task -- and
that rule lives here rather than in the schema, because a CHECK constraint
cannot see the parent row.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import WorkItem
from app.domain.codes import generate_work_item_code
from app.domain.enums import TaskEventType, WorkItemStatus, WorkItemType
from app.domain.work.events import record_event

#: What each type may hang from. ``None`` means the type is a root.
ALLOWED_PARENT_TYPE: dict[WorkItemType, WorkItemType | None] = {
    WorkItemType.INITIATIVE: None,
    WorkItemType.RESPONSIBILITY: WorkItemType.INITIATIVE,
    WorkItemType.TASK: WorkItemType.RESPONSIBILITY,
}

_CODE_ATTEMPTS = 10


class InvalidStructure(ValueError):
    """The requested shape is not a valid place in the tree.

    Carries a sentence meant for a person; it is relayed to users verbatim.
    """


async def create_work_item(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    item_type: WorkItemType,
    title: str,
    created_by_membership_id: uuid.UUID,
    parent: WorkItem | None = None,
    owner_membership_id: uuid.UUID | None = None,
    description: str | None = None,
    due_at: datetime | None = None,
) -> WorkItem:
    """Create one work item and record its creation."""
    _validate_placement(item_type, parent, organization_id)

    work_item = WorkItem(
        organization_id=organization_id,
        parent_id=parent.id if parent else None,
        type=item_type,
        title=title.strip(),
        description=description,
        owner_membership_id=owner_membership_id,
        created_by_membership_id=created_by_membership_id,
        status=WorkItemStatus.ACTIVE,
        due_at=due_at,
        short_code=await _allocate_code(session, organization_id, item_type),
        version=1,
    )
    session.add(work_item)
    await session.flush()

    await record_event(
        session,
        work_item,
        TaskEventType.WORK_CREATED,
        actor_membership_id=created_by_membership_id,
        type=item_type.value,
        title=work_item.title,
    )

    if owner_membership_id is not None:
        await record_event(
            session,
            work_item,
            TaskEventType.ASSIGNED,
            actor_membership_id=created_by_membership_id,
            assignee=str(owner_membership_id),
        )

    return work_item


def _validate_placement(
    item_type: WorkItemType, parent: WorkItem | None, organization_id: uuid.UUID
) -> None:
    expected = ALLOWED_PARENT_TYPE[item_type]

    if expected is None:
        if parent is not None:
            raise InvalidStructure(
                "An initiative is a top-level item and cannot sit under another."
            )
        return

    if parent is None:
        raise InvalidStructure(f"A {item_type.value.lower()} needs a {expected.value.lower()}.")

    if parent.type is not expected:
        raise InvalidStructure(
            f"A {item_type.value.lower()} belongs under a {expected.value.lower()}, "
            f"not under a {parent.type.value.lower()}."
        )

    if parent.organization_id != organization_id:
        raise InvalidStructure("That parent belongs to a different organization.")

    if parent.status is WorkItemStatus.CANCELLED:
        raise InvalidStructure(f"'{parent.title}' was cancelled, so nothing can be added to it.")


async def _allocate_code(
    session: AsyncSession, organization_id: uuid.UUID, item_type: WorkItemType
) -> str:
    """Find a code not already used in this organization.

    The unique constraint is the real guarantee; this loop only keeps the common
    case from hitting it.
    """
    for _ in range(_CODE_ATTEMPTS):
        candidate = generate_work_item_code(item_type)
        taken = await session.scalar(
            select(WorkItem.id).where(
                WorkItem.organization_id == organization_id,
                WorkItem.short_code == candidate,
            )
        )
        if taken is None:
            return candidate

    raise RuntimeError("could not allocate a unique short code")

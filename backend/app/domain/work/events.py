"""Appending to a work item's history."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TaskEvent, WorkItem
from app.domain.enums import TaskEventType


async def record_event(
    session: AsyncSession,
    work_item: WorkItem,
    event_type: TaskEventType,
    *,
    actor_membership_id: uuid.UUID | None,
    **payload: Any,
) -> TaskEvent:
    """Append one event.

    Events are written in the same transaction as the change they describe, so
    history cannot diverge from state.
    """
    event = TaskEvent(
        work_item_id=work_item.id,
        actor_membership_id=actor_membership_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    await session.flush()
    return event

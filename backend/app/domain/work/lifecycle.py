"""Task state transitions.

Legal moves are an explicit set rather than scattered conditionals, so the whole
lifecycle can be read in one place -- and so that adding a state later means
adding pairs here, not auditing call sites.

Every accepted move appends an event in the same transaction.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TaskEvent, WorkItem
from app.domain.enums import TaskEventType, WorkItemStatus, WorkItemType
from app.domain.work.events import record_event

S = WorkItemStatus

#: Tasks move through work. COMPLETE and CANCELLED are terminal.
TASK_TRANSITIONS: frozenset[tuple[S, S]] = frozenset(
    {
        (S.ACTIVE, S.IN_PROGRESS),
        (S.ACTIVE, S.COMPLETE),
        (S.IN_PROGRESS, S.COMPLETE),
        (S.ACTIVE, S.CANCELLED),
        (S.IN_PROGRESS, S.CANCELLED),
    }
)

#: Initiatives and responsibilities are containers. They are never "in progress"
#: or "complete" in their own right -- that is derived from the tasks beneath
#: them -- but they can be called off.
CONTAINER_TRANSITIONS: frozenset[tuple[S, S]] = frozenset({(S.ACTIVE, S.CANCELLED)})

_EVENT_FOR: dict[S, TaskEventType] = {
    S.IN_PROGRESS: TaskEventType.STARTED,
    S.COMPLETE: TaskEventType.COMPLETED,
    S.CANCELLED: TaskEventType.CANCELLED,
}


class InvalidTransition(ValueError):
    """The move is not legal from the item's current state.

    The message is written for a person and relayed verbatim.
    """


@dataclass(frozen=True, slots=True)
class TransitionResult:
    work_item: WorkItem
    changed: bool
    event: TaskEvent | None


def allowed_transitions(item_type: WorkItemType) -> frozenset[tuple[S, S]]:
    return TASK_TRANSITIONS if item_type is WorkItemType.TASK else CONTAINER_TRANSITIONS


async def transition(
    session: AsyncSession,
    work_item: WorkItem,
    to_status: WorkItemStatus,
    *,
    actor_membership_id: uuid.UUID | None,
) -> TransitionResult:
    """Move a work item to ``to_status``.

    Asking for the state it is already in is a no-op, not an error: someone who
    texts "done" twice has said something true both times, and the second one
    must not append a second COMPLETED event.
    """
    if work_item.status is to_status:
        return TransitionResult(work_item=work_item, changed=False, event=None)

    if (work_item.status, to_status) not in allowed_transitions(work_item.type):
        raise InvalidTransition(_explain(work_item, to_status))

    work_item.status = to_status
    work_item.version += 1
    await session.flush()

    event = await record_event(
        session,
        work_item,
        _EVENT_FOR[to_status],
        actor_membership_id=actor_membership_id,
        short_code=work_item.short_code,
    )

    return TransitionResult(work_item=work_item, changed=True, event=event)


def _explain(work_item: WorkItem, to_status: WorkItemStatus) -> str:
    noun = work_item.type.value.lower()

    if work_item.status is S.CANCELLED:
        return f"'{work_item.title}' was cancelled, so it can't be changed."
    if work_item.status is S.COMPLETE:
        return f"'{work_item.title}' is already finished."
    if work_item.type is not WorkItemType.TASK and to_status in (S.IN_PROGRESS, S.COMPLETE):
        return (
            f"'{work_item.title}' is a {noun}. Its progress comes from the tasks "
            "underneath it rather than being set directly."
        )

    return f"'{work_item.title}' can't go from {work_item.status.value} to {to_status.value}."


async def start_task(
    session: AsyncSession, work_item: WorkItem, *, actor_membership_id: uuid.UUID | None
) -> TransitionResult:
    return await transition(
        session, work_item, S.IN_PROGRESS, actor_membership_id=actor_membership_id
    )


async def complete_task(
    session: AsyncSession, work_item: WorkItem, *, actor_membership_id: uuid.UUID | None
) -> TransitionResult:
    return await transition(session, work_item, S.COMPLETE, actor_membership_id=actor_membership_id)


async def cancel_work_item(
    session: AsyncSession, work_item: WorkItem, *, actor_membership_id: uuid.UUID | None
) -> TransitionResult:
    return await transition(
        session, work_item, S.CANCELLED, actor_membership_id=actor_membership_id
    )

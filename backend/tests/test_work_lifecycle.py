"""Task state transitions."""

import pytest
from sqlalchemy import func, select

from app.database.models import TaskEvent
from app.domain.enums import TaskEventType, WorkItemStatus, WorkItemType
from app.domain.work import (
    InvalidTransition,
    cancel_work_item,
    complete_task,
    start_task,
    transition,
)
from tests.factories import make_child, make_initiative, make_tree

S = WorkItemStatus


async def _task(session):
    tree = await make_tree(session)
    initiative = await make_initiative(session, tree["organization"], tree["president"])
    marketing = await make_child(
        session,
        initiative,
        tree["president"],
        item_type=WorkItemType.RESPONSIBILITY,
        title="Marketing",
        owner=tree["vp_a"],
    )
    flyer = await make_child(
        session,
        marketing,
        tree["vp_a"],
        item_type=WorkItemType.TASK,
        title="Create flyer",
        owner=tree["member_a"],
    )
    return tree, initiative, marketing, flyer


async def _events(session, work_item, event_type=None):
    statement = (
        select(func.count()).select_from(TaskEvent).where(TaskEvent.work_item_id == work_item.id)
    )
    if event_type is not None:
        statement = statement.where(TaskEvent.event_type == event_type)
    return await session.scalar(statement)


class TestHappyPath:
    async def test_a_task_runs_from_active_to_complete(self, session):
        tree, _, _, flyer = await _task(session)
        actor = tree["member_a"].id

        started = await start_task(session, flyer, actor_membership_id=actor)
        assert started.changed is True
        assert flyer.status is S.IN_PROGRESS

        finished = await complete_task(session, flyer, actor_membership_id=actor)
        assert finished.changed is True
        assert flyer.status is S.COMPLETE

    async def test_a_task_may_be_finished_without_being_started(self, session):
        """People report work done without ever saying they began it."""
        tree, _, _, flyer = await _task(session)

        await complete_task(session, flyer, actor_membership_id=tree["member_a"].id)

        assert flyer.status is S.COMPLETE

    async def test_each_move_appends_one_event(self, session):
        tree, _, _, flyer = await _task(session)
        actor = tree["member_a"].id

        await start_task(session, flyer, actor_membership_id=actor)
        await complete_task(session, flyer, actor_membership_id=actor)

        assert await _events(session, flyer, TaskEventType.STARTED) == 1
        assert await _events(session, flyer, TaskEventType.COMPLETED) == 1

    async def test_every_move_bumps_the_version(self, session):
        tree, _, _, flyer = await _task(session)

        assert flyer.version == 1
        await start_task(session, flyer, actor_membership_id=tree["member_a"].id)
        assert flyer.version == 2


class TestIdempotency:
    async def test_finishing_twice_changes_nothing_the_second_time(self, session):
        """Someone texting "done" twice has said something true both times."""
        tree, _, _, flyer = await _task(session)
        actor = tree["member_a"].id

        first = await complete_task(session, flyer, actor_membership_id=actor)
        second = await complete_task(session, flyer, actor_membership_id=actor)

        assert first.changed is True
        assert second.changed is False
        assert second.event is None
        assert await _events(session, flyer, TaskEventType.COMPLETED) == 1

    async def test_a_no_op_does_not_bump_the_version(self, session):
        tree, _, _, flyer = await _task(session)
        actor = tree["member_a"].id

        await complete_task(session, flyer, actor_membership_id=actor)
        version = flyer.version
        await complete_task(session, flyer, actor_membership_id=actor)

        assert flyer.version == version


class TestTerminalStates:
    async def test_a_finished_task_cannot_be_restarted(self, session):
        tree, _, _, flyer = await _task(session)
        actor = tree["member_a"].id
        await complete_task(session, flyer, actor_membership_id=actor)

        with pytest.raises(InvalidTransition, match="already finished"):
            await start_task(session, flyer, actor_membership_id=actor)

    async def test_a_cancelled_task_cannot_be_changed(self, session):
        tree, _, _, flyer = await _task(session)
        actor = tree["president"].id
        await cancel_work_item(session, flyer, actor_membership_id=actor)

        with pytest.raises(InvalidTransition, match="cancelled"):
            await complete_task(session, flyer, actor_membership_id=actor)


class TestContainers:
    async def test_a_responsibility_cannot_be_started_or_finished(self, session):
        """Progress on a container is derived from the tasks beneath it."""
        tree, _, marketing, _ = await _task(session)
        actor = tree["president"].id

        with pytest.raises(InvalidTransition, match="tasks"):
            await start_task(session, marketing, actor_membership_id=actor)

        with pytest.raises(InvalidTransition, match="tasks"):
            await complete_task(session, marketing, actor_membership_id=actor)

    async def test_a_container_may_be_cancelled(self, session):
        tree, initiative, _, _ = await _task(session)

        result = await cancel_work_item(
            session, initiative, actor_membership_id=tree["president"].id
        )

        assert result.changed is True
        assert initiative.status is S.CANCELLED
        assert await _events(session, initiative, TaskEventType.CANCELLED) == 1


class TestTransitionTable:
    @pytest.mark.parametrize(
        ("start", "target"),
        [
            (S.ACTIVE, S.IN_PROGRESS),
            (S.ACTIVE, S.COMPLETE),
            (S.ACTIVE, S.CANCELLED),
            (S.IN_PROGRESS, S.COMPLETE),
            (S.IN_PROGRESS, S.CANCELLED),
        ],
    )
    async def test_every_documented_move_is_accepted(self, session, start, target):
        tree, _, _, flyer = await _task(session)
        actor = tree["member_a"].id

        if start is S.IN_PROGRESS:
            await start_task(session, flyer, actor_membership_id=actor)

        result = await transition(session, flyer, target, actor_membership_id=actor)

        assert result.changed is True
        assert flyer.status is target

    async def test_an_event_actor_may_be_absent(self, session):
        """Jenie itself can act, for example a scheduled cancellation."""
        tree, _, _, flyer = await _task(session)

        result = await cancel_work_item(session, flyer, actor_membership_id=None)

        assert result.event.actor_membership_id is None

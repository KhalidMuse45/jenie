"""Structure of the work tree."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.models import TaskEvent, WorkItem
from app.domain.enums import TaskEventType, WorkItemStatus, WorkItemType
from app.domain.work import (
    InvalidStructure,
    ancestors,
    cancel_work_item,
    create_work_item,
    subtree,
)
from tests.factories import make_child, make_initiative, make_organization, make_tree

RESPONSIBILITY = WorkItemType.RESPONSIBILITY
TASK = WorkItemType.TASK


async def _workshop(session):
    """Google AI Workshop with Marketing, Logistics, and three tasks."""
    tree = await make_tree(session)
    initiative = await make_initiative(session, tree["organization"], tree["president"])

    marketing = await make_child(
        session,
        initiative,
        tree["president"],
        item_type=RESPONSIBILITY,
        title="Marketing",
        owner=tree["vp_a"],
    )
    logistics = await make_child(
        session,
        initiative,
        tree["president"],
        item_type=RESPONSIBILITY,
        title="Logistics",
        owner=tree["vp_b"],
    )
    flyer = await make_child(
        session,
        marketing,
        tree["vp_a"],
        item_type=TASK,
        title="Create flyer",
        owner=tree["member_a"],
    )
    post = await make_child(
        session,
        marketing,
        tree["vp_a"],
        item_type=TASK,
        title="Publish post",
        owner=tree["member_b"],
    )
    room = await make_child(
        session,
        logistics,
        tree["vp_b"],
        item_type=TASK,
        title="Reserve room",
        owner=tree["member_c"],
    )

    return tree | {
        "initiative": initiative,
        "marketing": marketing,
        "logistics": logistics,
        "flyer": flyer,
        "post": post,
        "room": room,
    }


class TestStructure:
    async def test_the_documented_shape_is_accepted(self, session):
        work = await _workshop(session)

        assert work["initiative"].parent_id is None
        assert work["marketing"].parent_id == work["initiative"].id
        assert work["flyer"].parent_id == work["marketing"].id

    async def test_a_task_may_not_hang_directly_off_an_initiative(self, session):
        """Keeping every leaf under a responsibility is what makes progress a count."""
        tree = await make_tree(session)
        initiative = await make_initiative(session, tree["organization"], tree["president"])

        with pytest.raises(InvalidStructure, match="responsibility"):
            await make_child(
                session, initiative, tree["president"], item_type=TASK, title="Stray task"
            )

    async def test_a_responsibility_may_not_nest_inside_a_responsibility(self, session):
        work = await _workshop(session)

        with pytest.raises(InvalidStructure):
            await make_child(
                session,
                work["marketing"],
                work["president"],
                item_type=RESPONSIBILITY,
                title="Sub-marketing",
            )

    async def test_an_initiative_may_not_have_a_parent(self, session):
        work = await _workshop(session)

        with pytest.raises(InvalidStructure, match="top-level"):
            await create_work_item(
                session,
                organization_id=work["organization"].id,
                item_type=WorkItemType.INITIATIVE,
                title="Nested initiative",
                created_by_membership_id=work["president"].id,
                parent=work["marketing"],
            )

    async def test_nothing_can_be_added_to_cancelled_work(self, session):
        work = await _workshop(session)
        await cancel_work_item(session, work["marketing"], actor_membership_id=work["president"].id)

        with pytest.raises(InvalidStructure, match="cancelled"):
            await make_child(
                session, work["marketing"], work["vp_a"], item_type=TASK, title="Too late"
            )

    async def test_the_database_refuses_a_rootless_non_initiative(self, session):
        """The domain rule has a schema-level backstop."""
        tree = await make_tree(session)

        session.add(
            WorkItem(
                organization_id=tree["organization"].id,
                parent_id=None,
                type=RESPONSIBILITY,
                title="Orphan",
                created_by_membership_id=tree["president"].id,
                short_code="RESP-TEST",
            )
        )

        with pytest.raises(IntegrityError, match="only_initiatives_are_roots"):
            await session.flush()

    async def test_a_parent_from_another_organization_is_refused(self, session):
        work = await _workshop(session)
        other = await make_organization(session, "Other")

        with pytest.raises(InvalidStructure, match="different organization"):
            await create_work_item(
                session,
                organization_id=other.id,
                item_type=TASK,
                title="Cross-org task",
                created_by_membership_id=work["president"].id,
                parent=work["marketing"],
            )


class TestShortCodes:
    async def test_codes_are_prefixed_by_type(self, session):
        work = await _workshop(session)

        assert work["initiative"].short_code.startswith("INIT-")
        assert work["marketing"].short_code.startswith("RESP-")
        assert work["flyer"].short_code.startswith("TASK-")

    async def test_codes_avoid_characters_that_are_misread(self, session):
        work = await _workshop(session)

        suffix = work["flyer"].short_code.split("-")[1]

        assert len(suffix) == 4
        assert not set(suffix) & set("01ILOU")

    async def test_codes_are_unique_within_an_organization(self, session):
        work = await _workshop(session)

        codes = (
            await session.scalars(
                select(WorkItem.short_code).where(
                    WorkItem.organization_id == work["organization"].id
                )
            )
        ).all()

        assert len(codes) == len(set(codes)) == 6


class TestCreationEvents:
    async def test_creating_work_records_it(self, session):
        work = await _workshop(session)

        events = (
            await session.scalars(
                select(TaskEvent)
                .where(TaskEvent.work_item_id == work["flyer"].id)
                .order_by(TaskEvent.created_at)
            )
        ).all()

        assert [event.event_type for event in events] == [
            TaskEventType.WORK_CREATED,
            TaskEventType.ASSIGNED,
        ]

    async def test_unassigned_work_records_no_assignment(self, session):
        tree = await make_tree(session)
        initiative = await make_initiative(session, tree["organization"], tree["president"])

        count = await session.scalar(
            select(func.count())
            .select_from(TaskEvent)
            .where(
                TaskEvent.work_item_id == initiative.id,
                TaskEvent.event_type == TaskEventType.ASSIGNED,
            )
        )

        assert count == 0


class TestTraversal:
    async def test_subtree_includes_the_root_and_every_descendant(self, session):
        work = await _workshop(session)

        nodes = await subtree(session, work["initiative"].id)
        depths = {node.item.title: node.depth for node in nodes}

        assert depths == {
            "Google AI Workshop": 0,
            "Marketing": 1,
            "Logistics": 1,
            "Create flyer": 2,
            "Publish post": 2,
            "Reserve room": 2,
        }

    async def test_subtree_of_a_branch_excludes_siblings(self, session):
        work = await _workshop(session)

        titles = {node.item.title for node in await subtree(session, work["marketing"].id)}

        assert titles == {"Marketing", "Create flyer", "Publish post"}
        assert "Reserve room" not in titles

    async def test_subtree_of_a_leaf_is_just_the_leaf(self, session):
        work = await _workshop(session)

        nodes = await subtree(session, work["flyer"].id)

        assert [node.item.id for node in nodes] == [work["flyer"].id]

    async def test_ancestors_run_nearest_first(self, session):
        work = await _workshop(session)

        chain = [node.item.title for node in await ancestors(session, work["flyer"].id)]

        assert chain == ["Marketing", "Google AI Workshop"]

    async def test_a_cycle_terminates_instead_of_hanging(self, session):
        """Nothing stops a parent pointer being moved into its own subtree."""
        import asyncio

        work = await _workshop(session)

        work["initiative"].parent_id = work["marketing"].id
        work["initiative"].type = WorkItemType.RESPONSIBILITY
        await session.flush()

        nodes = await asyncio.wait_for(subtree(session, work["marketing"].id), timeout=10)

        assert {node.item.title for node in nodes} >= {"Marketing", "Google AI Workshop"}


class TestDefaults:
    async def test_new_work_starts_active_at_version_one(self, session):
        work = await _workshop(session)

        assert work["flyer"].status is WorkItemStatus.ACTIVE
        assert work["flyer"].version == 1

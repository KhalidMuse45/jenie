"""Building and submitting delegation plans.

Nothing in this file should create a WorkItem. A plan is a proposal until it is
approved, and that is what most of these tests are really checking.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.models import DelegationPlan, WorkItem
from app.domain.delegation import (
    InvalidPlanState,
    PlanNotEditable,
    PlanNotReady,
    add_item,
    create_plan,
    list_items,
    remove_item,
    submit_plan,
    update_item,
)
from app.domain.enums import DelegationPlanStatus, WorkItemType
from app.domain.work import cancel_work_item
from tests.factories import make_child, make_initiative, make_tree

NEXT_WEEK = datetime.now(UTC) + timedelta(days=7)
LAST_WEEK = datetime.now(UTC) - timedelta(days=7)


async def _marketing(session):
    """Google AI Workshop → Marketing, owned by the VP."""
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
    return tree, initiative, marketing


async def _full_plan(session):
    """A submittable plan: two tasks, both assigned beneath the creator."""
    tree, initiative, marketing = await _marketing(session)
    plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
    await add_item(
        session,
        plan,
        title="Create flyer",
        proposed_assignee_membership_id=tree["member_a"].id,
        proposed_due_at=NEXT_WEEK,
    )
    await add_item(
        session,
        plan,
        title="Publish post",
        proposed_assignee_membership_id=tree["member_b"].id,
        proposed_due_at=NEXT_WEEK,
    )
    return tree, marketing, plan


async def _work_item_count(session) -> int:
    return await session.scalar(select(func.count()).select_from(WorkItem))


class TestCreatingPlans:
    async def test_a_plan_starts_as_an_empty_draft(self, session):
        tree, _, marketing = await _marketing(session)

        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

        assert plan.status is DelegationPlanStatus.DRAFT
        assert await list_items(session, plan) == []
        assert plan.short_code.startswith("PLAN-")
        assert plan.required_approver_membership_id is None
        assert plan.submitted_at is None

    async def test_a_plan_breaks_down_a_responsibility_not_an_initiative(self, session):
        tree, initiative, _ = await _marketing(session)

        with pytest.raises(PlanNotReady, match="responsibility"):
            await create_plan(
                session, scope=initiative, created_by_membership_id=tree["president"].id
            )

    async def test_cancelled_work_cannot_be_planned(self, session):
        tree, _, marketing = await _marketing(session)
        await cancel_work_item(session, marketing, actor_membership_id=tree["president"].id)

        with pytest.raises(PlanNotReady, match="cancelled"):
            await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

    async def test_only_one_plan_may_be_open_for_a_responsibility(self, session):
        """Two open plans makes "approve Sarah's plan" ambiguous."""
        tree, _, marketing = await _marketing(session)
        await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

        with pytest.raises(IntegrityError, match="one_open_per_scope"):
            await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)


class TestEditingDrafts:
    async def test_items_keep_the_order_they_were_added(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

        for title in ("First", "Second", "Third"):
            await add_item(session, plan, title=title)

        items = await list_items(session, plan)
        assert [item.title for item in items] == ["First", "Second", "Third"]
        assert [item.sort_order for item in items] == [0, 1, 2]

    async def test_every_change_moves_the_version(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        assert plan.version == 1

        item = await add_item(session, plan, title="Create flyer")
        assert plan.version == 2

        await update_item(session, plan, item, title="Create event flyer")
        assert plan.version == 3

        await remove_item(session, plan, item)
        assert plan.version == 4

    async def test_clearing_a_field_differs_from_leaving_it_alone(self, session):
        """The sentinel exists so both are expressible."""
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        item = await add_item(
            session,
            plan,
            title="Create flyer",
            proposed_assignee_membership_id=tree["member_a"].id,
            proposed_due_at=NEXT_WEEK,
        )

        await update_item(session, plan, item, title="Renamed")
        assert item.proposed_assignee_membership_id == tree["member_a"].id

        await update_item(session, plan, item, proposed_assignee_membership_id=None)
        assert item.proposed_assignee_membership_id is None
        assert item.proposed_due_at == NEXT_WEEK

    async def test_an_item_from_another_plan_is_refused(self, session):
        tree, initiative, marketing = await _marketing(session)
        logistics = await make_child(
            session,
            initiative,
            tree["president"],
            item_type=WorkItemType.RESPONSIBILITY,
            title="Logistics",
            owner=tree["vp_b"],
        )
        plan_a = await create_plan(
            session, scope=marketing, created_by_membership_id=tree["vp_a"].id
        )
        plan_b = await create_plan(
            session, scope=logistics, created_by_membership_id=tree["vp_b"].id
        )
        stray = await add_item(session, plan_b, title="Reserve room")

        with pytest.raises(PlanNotEditable, match="different plan"):
            await remove_item(session, plan_a, stray)


class TestSubmitting:
    async def test_submitting_routes_to_the_creator_s_manager(self, session):
        tree, _, plan = await _full_plan(session)

        await submit_plan(session, plan)

        assert plan.status is DelegationPlanStatus.PENDING_APPROVAL
        assert plan.required_approver_membership_id == tree["president"].id
        assert plan.submitted_at is not None

    async def test_someone_at_the_top_approves_their_own_plan(self, session):
        """A formality, not an escalation: they can already act directly."""
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(
            session, scope=marketing, created_by_membership_id=tree["president"].id
        )
        await add_item(
            session,
            plan,
            title="Create flyer",
            proposed_assignee_membership_id=tree["member_a"].id,
            proposed_due_at=NEXT_WEEK,
        )

        await submit_plan(session, plan)

        assert plan.required_approver_membership_id == tree["president"].id

    async def test_an_empty_plan_cannot_be_sent(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

        with pytest.raises(PlanNotReady, match="empty"):
            await submit_plan(session, plan)

    async def test_a_task_with_nobody_on_it_names_itself(self, session):
        """The person who wrote the plan is the one who hears about its problems."""
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        await add_item(session, plan, title="Create flyer", proposed_due_at=NEXT_WEEK)

        with pytest.raises(PlanNotReady, match="Create flyer"):
            await submit_plan(session, plan)

    async def test_a_task_with_no_due_date_names_itself(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        await add_item(
            session,
            plan,
            title="Create flyer",
            proposed_assignee_membership_id=tree["member_a"].id,
        )

        with pytest.raises(PlanNotReady, match="No due date"):
            await submit_plan(session, plan)

    async def test_a_due_date_in_the_past_is_refused(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        await add_item(
            session,
            plan,
            title="Create flyer",
            proposed_assignee_membership_id=tree["member_a"].id,
            proposed_due_at=LAST_WEEK,
        )

        with pytest.raises(PlanNotReady, match="past due"):
            await submit_plan(session, plan)

    async def test_work_cannot_be_proposed_outside_the_creator_s_branch(self, session):
        """Approval would otherwise be a route to assigning work sideways."""
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        await add_item(
            session,
            plan,
            title="Reserve room",
            proposed_assignee_membership_id=tree["member_c"].id,  # under the other VP
            proposed_due_at=NEXT_WEEK,
        )

        with pytest.raises(PlanNotReady, match="report to you"):
            await submit_plan(session, plan)

    async def test_a_creator_may_propose_work_for_themselves(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        await add_item(
            session,
            plan,
            title="Send the email myself",
            proposed_assignee_membership_id=tree["vp_a"].id,
            proposed_due_at=NEXT_WEEK,
        )

        await submit_plan(session, plan)

        assert plan.status is DelegationPlanStatus.PENDING_APPROVAL

    async def test_a_plan_cannot_be_sent_twice(self, session):
        _, _, plan = await _full_plan(session)
        await submit_plan(session, plan)

        with pytest.raises(InvalidPlanState, match="already been sent"):
            await submit_plan(session, plan)

    async def test_a_submitted_plan_is_still_editable(self, session):
        """The approver adjusts it in place; who may is the permission engine's call."""
        tree, _, plan = await _full_plan(session)
        await submit_plan(session, plan)

        items = await list_items(session, plan)
        await update_item(session, plan, items[0], title="Create event flyer")

        assert items[0].title == "Create event flyer"


class TestNothingIsRealYet:
    async def test_building_and_submitting_creates_no_work(self, session):
        """The heart of it. Until approval, nobody has been assigned anything."""
        before = await _work_item_count(session)

        _, _, plan = await _full_plan(session)
        await submit_plan(session, plan)

        assert plan.status is DelegationPlanStatus.PENDING_APPROVAL
        assert len(await list_items(session, plan)) == 2
        # Two proposed tasks, and not one new work item: only the initiative and
        # the responsibility that existed beforehand.
        assert await _work_item_count(session) == before + 2
        assert (
            await session.scalar(
                select(func.count()).select_from(WorkItem).where(WorkItem.type == WorkItemType.TASK)
            )
            == 0
        )


class TestSchemaGuards:
    async def test_the_database_refuses_a_pending_plan_with_no_approver(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

        plan.status = DelegationPlanStatus.PENDING_APPROVAL
        plan.submitted_at = datetime.now(UTC)

        with pytest.raises(IntegrityError, match="submitted_plans_have_an_approver"):
            await session.flush()

    async def test_the_database_ties_approved_at_to_the_status(self, session):
        tree, _, marketing = await _marketing(session)
        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)

        plan.approved_at = datetime.now(UTC)

        with pytest.raises(IntegrityError, match="approved_at_matches_status"):
            await session.flush()

    async def test_plan_codes_are_unique_within_an_organization(self, session):
        tree, initiative, marketing = await _marketing(session)
        logistics = await make_child(
            session,
            initiative,
            tree["president"],
            item_type=WorkItemType.RESPONSIBILITY,
            title="Logistics",
            owner=tree["vp_b"],
        )

        first = await create_plan(
            session, scope=marketing, created_by_membership_id=tree["vp_a"].id
        )
        second = await create_plan(
            session, scope=logistics, created_by_membership_id=tree["vp_b"].id
        )

        codes = (await session.scalars(select(DelegationPlan.short_code))).all()
        assert first.short_code != second.short_code
        assert len(codes) == len(set(codes))

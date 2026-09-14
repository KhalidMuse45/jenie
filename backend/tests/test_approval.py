"""Approving and rejecting delegation plans.

The acceptance criteria for the delegation milestone live here: a plan becomes
exactly the tasks it proposed, told exactly the people it named, once.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.database.models import (
    Approval,
    AuditEvent,
    Membership,
    OutboundMessage,
    TaskEvent,
    WorkItem,
)
from app.domain.delegation import (
    InvalidPlanState,
    PlanChanged,
    PlanNotEditable,
    add_item,
    approve_plan,
    create_plan,
    reject_plan,
    submit_plan,
    update_item,
)
from app.domain.delegation.service import list_items
from app.domain.enums import (
    ApprovalDecision,
    AuditAction,
    DelegationPlanStatus,
    OutboundMessageStatus,
    OutboundMessageType,
    TaskEventType,
    WorkItemStatus,
    WorkItemType,
)
from app.domain.permissions import PermissionDenied, load_actor
from app.domain.work import create_work_item
from app.seed import seed, stable_id
from tests.factories import make_child, make_initiative, make_member, make_tree

WEDNESDAY = datetime.now(UTC) + timedelta(days=3)
FRIDAY = datetime.now(UTC) + timedelta(days=5)


def member_id(key: str):
    return stable_id("membership", "colorstack-umn", key)


async def _workshop(session):
    """The scenario from the specification.

    Khalid (President) → Sarah (VP) → Izra, Marwa. Sarah owns Marketing for the
    Google AI Workshop and proposes three tasks.
    """
    organization = await seed(session)
    khalid = await session.get(Membership, member_id("khalid"))
    sarah = await session.get(Membership, member_id("sarah"))
    izra = await session.get(Membership, member_id("izra"))
    marwa = await session.get(Membership, member_id("marwa"))

    initiative = await create_work_item(
        session,
        organization_id=organization.id,
        item_type=WorkItemType.INITIATIVE,
        title="Google AI Workshop",
        created_by_membership_id=khalid.id,
    )
    marketing = await create_work_item(
        session,
        organization_id=organization.id,
        item_type=WorkItemType.RESPONSIBILITY,
        title="Marketing",
        created_by_membership_id=khalid.id,
        parent=initiative,
        owner_membership_id=sarah.id,
    )

    plan = await create_plan(session, scope=marketing, created_by_membership_id=sarah.id)
    await add_item(
        session,
        plan,
        title="Create event flyer",
        proposed_assignee_membership_id=izra.id,
        proposed_due_at=WEDNESDAY,
    )
    await add_item(
        session,
        plan,
        title="Publish Instagram announcement",
        proposed_assignee_membership_id=marwa.id,
        proposed_due_at=FRIDAY,
    )
    await add_item(
        session,
        plan,
        title="Send member announcement",
        proposed_assignee_membership_id=sarah.id,
        proposed_due_at=FRIDAY,
    )

    return {
        "organization": organization,
        "khalid": khalid,
        "sarah": sarah,
        "izra": izra,
        "marwa": marwa,
        "initiative": initiative,
        "marketing": marketing,
        "plan": plan,
    }


async def _tasks(session):
    return list(await session.scalars(select(WorkItem).where(WorkItem.type == WorkItemType.TASK)))


async def _outbox(session, message_type=None):
    statement = select(OutboundMessage)
    if message_type is not None:
        statement = statement.where(OutboundMessage.message_type == message_type)
    return list(await session.scalars(statement))


class TestTheMilestoneAcceptance:
    async def test_submitting_assigns_nobody(self, session):
        work = await _workshop(session)

        await submit_plan(session, work["plan"])

        assert work["plan"].status is DelegationPlanStatus.PENDING_APPROVAL
        assert await _tasks(session) == []

    async def test_submitting_tells_the_approver(self, session):
        work = await _workshop(session)

        await submit_plan(session, work["plan"])

        queued = await _outbox(session, OutboundMessageType.PLAN_SUBMITTED)
        assert len(queued) == 1
        assert queued[0].recipient_membership_id == work["khalid"].id
        assert "3 proposed tasks" in queued[0].body
        assert work["plan"].short_code in queued[0].body

    async def test_approval_creates_exactly_the_proposed_tasks(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        outcome = await approve_plan(session, work["plan"].id, actor=khalid)

        assert len(outcome.created_work_items) == 3

        created = {item.title: item for item in await _tasks(session)}
        assert set(created) == {
            "Create event flyer",
            "Publish Instagram announcement",
            "Send member announcement",
        }
        assert created["Create event flyer"].owner_membership_id == work["izra"].id
        assert created["Publish Instagram announcement"].owner_membership_id == work["marwa"].id
        assert created["Send member announcement"].owner_membership_id == work["sarah"].id
        assert created["Create event flyer"].due_at == WEDNESDAY

    async def test_new_tasks_hang_under_the_planned_responsibility(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        outcome = await approve_plan(session, work["plan"].id, actor=khalid)

        for item in outcome.created_work_items:
            assert item.parent_id == work["marketing"].id
            assert item.status is WorkItemStatus.ACTIVE

    async def test_everyone_named_is_queued_exactly_once(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        await approve_plan(session, work["plan"].id, actor=khalid)

        assignments = await _outbox(session, OutboundMessageType.ASSIGNMENT)
        assert len(assignments) == 3
        assert {message.recipient_membership_id for message in assignments} == {
            work["izra"].id,
            work["marwa"].id,
            work["sarah"].id,
        }
        assert all(message.status is OutboundMessageStatus.PENDING for message in assignments)

        # And the person who wrote the plan hears that it went through.
        approved = await _outbox(session, OutboundMessageType.PLAN_APPROVED)
        assert [message.recipient_membership_id for message in approved] == [work["sarah"].id]

    async def test_the_assignment_message_says_who_decided_what(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)
        await approve_plan(session, work["plan"].id, actor=khalid)

        body = next(
            message.body
            for message in await _outbox(session, OutboundMessageType.ASSIGNMENT)
            if message.recipient_membership_id == work["izra"].id
        )

        assert "Google AI Workshop -> Marketing" in body
        assert "Create event flyer" in body
        assert "Delegated by Sarah - approved by Khalid" in body
        assert "TASK-" in body

    async def test_an_approved_plan_becomes_immutable(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)
        items = await list_items(session, work["plan"])

        await approve_plan(session, work["plan"].id, actor=khalid)

        assert work["plan"].status is DelegationPlanStatus.APPROVED
        assert work["plan"].approved_at is not None

        with pytest.raises(PlanNotEditable, match="already approved"):
            await update_item(session, work["plan"], items[0], title="Too late")


class TestRejection:
    async def test_rejection_creates_no_work(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        outcome = await reject_plan(
            session, work["plan"].id, actor=khalid, comment="Too many people on this."
        )

        assert work["plan"].status is DelegationPlanStatus.REJECTED
        assert outcome.created_work_items == []
        assert await _tasks(session) == []
        assert await _outbox(session, OutboundMessageType.ASSIGNMENT) == []

    async def test_rejection_passes_the_comment_back(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        await reject_plan(session, work["plan"].id, actor=khalid, comment="Too many people.")

        queued = await _outbox(session, OutboundMessageType.PLAN_REJECTED)
        assert len(queued) == 1
        assert queued[0].recipient_membership_id == work["sarah"].id
        assert "Too many people." in queued[0].body


class TestIdempotency:
    async def test_approving_twice_creates_one_set_of_tasks(self, session):
        """A retried webhook or a second text must not double the work."""
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        first = await approve_plan(session, work["plan"].id, actor=khalid)
        second = await approve_plan(session, work["plan"].id, actor=khalid)

        assert first.already_decided is False
        assert second.already_decided is True
        assert second.created_work_items == []
        assert second.notifications == []

        assert len(await _tasks(session)) == 3
        assert len(await _outbox(session, OutboundMessageType.ASSIGNMENT)) == 3
        assert (await session.scalar(select(func.count()).select_from(Approval))) == 1

    async def test_rejecting_twice_is_also_a_no_op(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        await reject_plan(session, work["plan"].id, actor=khalid)
        second = await reject_plan(session, work["plan"].id, actor=khalid)

        assert second.already_decided is True
        assert len(await _outbox(session, OutboundMessageType.PLAN_REJECTED)) == 1

    async def test_a_decided_plan_cannot_be_decided_the_other_way(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)
        await approve_plan(session, work["plan"].id, actor=khalid)

        with pytest.raises(InvalidPlanState, match="already been decided"):
            await reject_plan(session, work["plan"].id, actor=khalid)


class TestGuards:
    async def test_a_draft_cannot_be_approved(self, session):
        work = await _workshop(session)
        khalid = await load_actor(session, work["khalid"].id)

        with pytest.raises(InvalidPlanState, match="hasn't been sent"):
            await approve_plan(session, work["plan"].id, actor=khalid)

    async def test_only_the_named_approver_may_approve(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        sarah = await load_actor(session, work["sarah"].id)

        with pytest.raises(PermissionDenied, match="sent to someone else"):
            await approve_plan(session, work["plan"].id, actor=sarah)

        assert await _tasks(session) == []

    async def test_an_edit_invalidates_a_stale_approval(self, session):
        """The President reads a plan, someone changes it, the President says yes.

        Without the version check that yes would attach to text they never saw.
        """
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)
        seen_version = work["plan"].version

        items = await list_items(session, work["plan"])
        await update_item(session, work["plan"], items[0], proposed_due_at=FRIDAY)

        with pytest.raises(PlanChanged, match="changed after I showed it to you"):
            await approve_plan(
                session, work["plan"].id, actor=khalid, expected_version=seen_version
            )

        assert await _tasks(session) == []

    async def test_approving_the_version_you_read_succeeds(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        outcome = await approve_plan(
            session, work["plan"].id, actor=khalid, expected_version=work["plan"].version
        )

        assert len(outcome.created_work_items) == 3


class TestTheApproverAdjustsAndApproves:
    async def test_the_approver_may_change_a_due_date_then_approve(self, session):
        """The moment the product is built around.

        "Make the flyer Wednesday instead. Everything else is good." — one
        gesture, and the tasks that appear carry the corrected date.
        """
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        items = await list_items(session, work["plan"])
        flyer = next(item for item in items if item.title == "Create event flyer")
        await update_item(session, work["plan"], flyer, proposed_due_at=FRIDAY)

        outcome = await approve_plan(session, work["plan"].id, actor=khalid)

        created = {item.title: item for item in outcome.created_work_items}
        assert created["Create event flyer"].due_at == FRIDAY
        assert created["Publish Instagram announcement"].due_at == FRIDAY


class TestTheRecord:
    async def test_the_approval_names_the_version_it_approved(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)
        decided_version = work["plan"].version

        outcome = await approve_plan(session, work["plan"].id, actor=khalid)

        assert outcome.approval.decision is ApprovalDecision.APPROVED
        assert outcome.approval.approver_membership_id == work["khalid"].id
        assert outcome.approval.plan_version == decided_version
        # The plan itself has moved on; the record has not.
        assert work["plan"].version == decided_version + 1

    async def test_approval_writes_an_audit_entry(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        await approve_plan(session, work["plan"].id, actor=khalid)

        event = await session.scalar(select(AuditEvent))
        assert event.action is AuditAction.APPROVE_PLAN
        assert event.actor_membership_id == work["khalid"].id
        assert event.target_id == work["plan"].id
        assert event.before_state["status"] == "PENDING_APPROVAL"
        assert event.after_state["status"] == "APPROVED"
        assert len(event.payload["created_work_item_ids"]) == 3

    async def test_every_new_task_records_its_creation_and_assignment(self, session):
        work = await _workshop(session)
        await submit_plan(session, work["plan"])
        khalid = await load_actor(session, work["khalid"].id)

        outcome = await approve_plan(session, work["plan"].id, actor=khalid)

        for item in outcome.created_work_items:
            kinds = list(
                await session.scalars(
                    select(TaskEvent.event_type)
                    .where(TaskEvent.work_item_id == item.id)
                    .order_by(TaskEvent.created_at)
                )
            )
            assert kinds == [TaskEventType.WORK_CREATED, TaskEventType.ASSIGNED]


class TestUnreachablePeople:
    async def test_an_unreachable_assignee_still_gets_a_row_marked_failed(self, session):
        """ "Nobody told Marwa" has to be visible, not a silent gap."""
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
        # make_member creates no messaging identity.
        unreachable = await make_member(
            session, tree["organization"], "ghost", manager=tree["vp_a"]
        )

        plan = await create_plan(session, scope=marketing, created_by_membership_id=tree["vp_a"].id)
        await add_item(
            session,
            plan,
            title="Do a thing",
            proposed_assignee_membership_id=unreachable.id,
            proposed_due_at=FRIDAY,
        )
        await submit_plan(session, plan)

        president = await load_actor(session, tree["president"].id)
        outcome = await approve_plan(session, plan.id, actor=president)

        assert len(outcome.created_work_items) == 1
        assignments = await _outbox(session, OutboundMessageType.ASSIGNMENT)
        assert len(assignments) == 1
        assert assignments[0].status is OutboundMessageStatus.FAILED
        assert assignments[0].destination is None
        assert "No verified messaging identity" in assignments[0].last_error


class TestSelfApproval:
    async def test_the_top_of_the_organization_is_not_told_about_itself(self, session):
        work = await _workshop(session)
        khalid_membership = work["khalid"]

        # Its own responsibility: Marketing already has a plan open, and only
        # one may be in flight per scope.
        logistics = await create_work_item(
            session,
            organization_id=work["organization"].id,
            item_type=WorkItemType.RESPONSIBILITY,
            title="Logistics",
            created_by_membership_id=khalid_membership.id,
            parent=work["initiative"],
            owner_membership_id=khalid_membership.id,
        )
        plan = await create_plan(
            session, scope=logistics, created_by_membership_id=khalid_membership.id
        )

        await add_item(
            session,
            plan,
            title="Handle it myself",
            proposed_assignee_membership_id=khalid_membership.id,
            proposed_due_at=FRIDAY,
        )
        await submit_plan(session, plan)

        assert plan.required_approver_membership_id == khalid_membership.id
        assert await _outbox(session, OutboundMessageType.PLAN_SUBMITTED) == []

        khalid = await load_actor(session, khalid_membership.id)
        await approve_plan(session, plan.id, actor=khalid)

        assert await _outbox(session, OutboundMessageType.PLAN_APPROVED) == []
        assert len(await _outbox(session, OutboundMessageType.ASSIGNMENT)) == 1

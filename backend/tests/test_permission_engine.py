"""The permission engine, exercised without a database.

``can`` is pure, so the policy can be tested directly on constructed actors.
"""

import re
import uuid

import pytest

from app.domain.enums import MembershipStatus, RoleType
from app.domain.permissions import (
    Action,
    Actor,
    DelegationSubject,
    MemberSubject,
    PermissionDenied,
    WorkSubject,
    can,
    require,
)
from app.domain.permissions.engine import _RULES

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()


def make_actor(
    *,
    membership_id: uuid.UUID | None = None,
    organization_id: uuid.UUID = ORG,
    role: RoleType = RoleType.VP,
    is_superadmin: bool = False,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    below: tuple[uuid.UUID, ...] = (),
) -> Actor:
    membership_id = membership_id or uuid.uuid4()
    return Actor(
        membership_id=membership_id,
        organization_id=organization_id,
        role_type=role,
        is_superadmin=is_superadmin,
        status=status,
        scope=frozenset({membership_id, *below}),
    )


def member_in(organization_id: uuid.UUID = ORG, membership_id: uuid.UUID | None = None):
    return MemberSubject(
        organization_id=organization_id,
        membership_id=membership_id or uuid.uuid4(),
    )


def work_in(
    organization_id: uuid.UUID = ORG,
    *,
    owner: uuid.UUID | None = None,
    creator: uuid.UUID | None = None,
) -> WorkSubject:
    return WorkSubject(
        organization_id=organization_id,
        work_item_id=uuid.uuid4(),
        owner_membership_id=owner,
        created_by_membership_id=creator or uuid.uuid4(),
    )


def delegation_in(
    organization_id: uuid.UUID = ORG,
    *,
    owner: uuid.UUID | None = None,
    to: uuid.UUID | None = None,
) -> DelegationSubject:
    return DelegationSubject(
        organization_id=organization_id,
        work_item_id=uuid.uuid4(),
        owner_membership_id=owner,
        created_by_membership_id=uuid.uuid4(),
        proposed_owner_membership_id=to or uuid.uuid4(),
    )


WORK_ACTIONS = {
    Action.VIEW_WORK_ITEM,
    Action.EDIT_WORK_ITEM,
    Action.CANCEL_WORK_ITEM,
    Action.CREATE_WORK_ITEM,
    Action.START_TASK,
    Action.COMPLETE_TASK,
}


def subject_for_action(action: Action, organization_id: uuid.UUID = ORG):
    """The subject type each action expects.

    Pairing the wrong one raises, which is the engine working as intended.
    """
    if action in WORK_ACTIONS:
        return work_in(organization_id)
    if action is Action.DELEGATE_RESPONSIBILITY:
        return delegation_in(organization_id)
    return member_in(organization_id)


class TestGates:
    """Checks that run before any rule is consulted."""

    def test_an_inactive_membership_may_do_nothing(self):
        actor = make_actor(status=MembershipStatus.INACTIVE)

        decision = can(actor, Action.VIEW_MEMBER_WORK, member_in())

        assert not decision
        assert "not active" in decision.reason

    def test_an_inactive_superadmin_may_do_nothing(self):
        """Losing the seat has to remove the authority that came with it."""
        actor = make_actor(is_superadmin=True, status=MembershipStatus.INACTIVE)

        assert not can(actor, Action.MANAGE_HIERARCHY, member_in())

    def test_a_superadmin_has_no_authority_in_another_organization(self):
        """The organization check must run before the superadmin shortcut.

        Reversing that order would let an administrator of one organization act
        on another's data.
        """
        actor = make_actor(is_superadmin=True)

        decision = can(actor, Action.VIEW_MEMBER_WORK, member_in(organization_id=OTHER_ORG))

        assert not decision
        assert "different organization" in decision.reason

    def test_a_superadmin_may_take_any_action_in_their_own_organization(self):
        actor = make_actor(is_superadmin=True)

        for action in Action:
            assert can(actor, action, subject_for_action(action)), action


class TestFailClosed:
    def test_an_action_without_a_rule_is_denied(self):
        """The engine is closed. New resources add rules; they do not relax this."""
        actor = make_actor()
        unruled = [action for action in Action if action not in _RULES]

        assert unruled, "expected some actions to have no rule yet"
        for action in unruled:
            assert not can(actor, action, subject_for_action(action)), action

    def test_pairing_an_action_with_the_wrong_subject_raises(self):
        """A coding mistake must not quietly look like a permissions problem."""
        actor = make_actor()

        with pytest.raises(TypeError):
            can(actor, Action.VIEW_MEMBER_WORK, None)


class TestViewMemberWork:
    def test_a_member_may_view_their_own_work(self):
        actor = make_actor(role=RoleType.MEMBER)

        assert can(actor, Action.VIEW_MEMBER_WORK, member_in(membership_id=actor.membership_id))

    def test_a_manager_may_view_work_beneath_them(self):
        report = uuid.uuid4()
        actor = make_actor(below=(report,))

        assert can(actor, Action.VIEW_MEMBER_WORK, member_in(membership_id=report))

    def test_a_member_may_not_view_a_peer(self):
        actor = make_actor(role=RoleType.MEMBER)

        decision = can(actor, Action.VIEW_MEMBER_WORK, member_in())

        assert not decision
        assert "report to you" in decision.reason

    def test_a_member_may_not_view_their_manager(self):
        manager = uuid.uuid4()
        actor = make_actor(role=RoleType.MEMBER)

        assert not can(actor, Action.VIEW_MEMBER_WORK, member_in(membership_id=manager))


class TestSuperadminOnlyActions:
    @pytest.mark.parametrize(
        "action",
        [Action.MANAGE_MEMBERS, Action.MANAGE_HIERARCHY, Action.VIEW_ORGANIZATION_WORK],
    )
    def test_a_vice_president_is_refused(self, action):
        actor = make_actor(role=RoleType.VP, below=(uuid.uuid4(),))

        decision = can(actor, action, member_in())

        assert not decision
        assert "organization administrator" in decision.reason


class TestRequire:
    def test_require_is_silent_when_allowed(self):
        actor = make_actor(is_superadmin=True)

        assert require(actor, Action.MANAGE_MEMBERS, member_in()) is None

    def test_require_raises_carrying_the_reason(self):
        actor = make_actor(role=RoleType.MEMBER)

        with pytest.raises(PermissionDenied) as raised:
            require(actor, Action.MANAGE_HIERARCHY, member_in())

        assert raised.value.reason == str(raised.value)
        assert "organization administrator" in raised.value.reason


def test_denial_reasons_are_written_for_people():
    """Reasons reach users verbatim over iMessage.

    They must read as sentences and must not leak identifiers or internal state.
    """
    uuid_like = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}", re.IGNORECASE)

    actors = [
        make_actor(role=RoleType.MEMBER),
        make_actor(status=MembershipStatus.INACTIVE),
        make_actor(is_superadmin=True, organization_id=OTHER_ORG),
    ]

    for actor in actors:
        for action in Action:
            subject = subject_for_action(action, actor.organization_id)
            decision = can(actor, action, subject)
            if decision.allowed:
                continue
            assert decision.reason.endswith("."), decision.reason
            assert decision.reason[0].isupper(), decision.reason
            assert not uuid_like.search(decision.reason), decision.reason


class TestWorkItems:
    def test_an_owner_may_see_and_change_their_own_work(self):
        actor = make_actor(role=RoleType.MEMBER)
        work = work_in(owner=actor.membership_id)

        assert can(actor, Action.VIEW_WORK_ITEM, work)
        assert can(actor, Action.EDIT_WORK_ITEM, work)
        assert can(actor, Action.CANCEL_WORK_ITEM, work)

    def test_a_manager_may_change_a_report_s_work(self):
        report = uuid.uuid4()
        actor = make_actor(below=(report,))

        assert can(actor, Action.EDIT_WORK_ITEM, work_in(owner=report))

    def test_a_peer_may_not_see_work(self):
        actor = make_actor(role=RoleType.MEMBER)

        decision = can(actor, Action.VIEW_WORK_ITEM, work_in(owner=uuid.uuid4()))

        assert not decision
        assert "reports to you" in decision.reason

    def test_unowned_work_follows_whoever_created_it(self):
        """An initiative exists before anyone owns it."""
        report = uuid.uuid4()
        actor = make_actor(below=(report,))

        assert can(actor, Action.VIEW_WORK_ITEM, work_in(owner=None, creator=report))
        assert not can(actor, Action.VIEW_WORK_ITEM, work_in(owner=None, creator=uuid.uuid4()))

    def test_only_the_assignee_may_start_or_finish_a_task(self):
        """Narrower than editing on purpose.

        A manager can change or cancel a report's task, but saying it is done is
        the assignee's to say.
        """
        report = uuid.uuid4()
        manager = make_actor(below=(report,))
        work = work_in(owner=report)

        assert can(manager, Action.EDIT_WORK_ITEM, work)

        decision = can(manager, Action.COMPLETE_TASK, work)
        assert not decision
        assert "assigned to" in decision.reason

    def test_the_assignee_may_start_and_finish(self):
        actor = make_actor(role=RoleType.MEMBER)
        work = work_in(owner=actor.membership_id)

        assert can(actor, Action.START_TASK, work)
        assert can(actor, Action.COMPLETE_TASK, work)

    def test_adding_beneath_requires_responsibility_for_the_parent(self):
        report = uuid.uuid4()
        actor = make_actor(below=(report,))

        assert can(actor, Action.CREATE_WORK_ITEM, work_in(owner=report))
        assert not can(actor, Action.CREATE_WORK_ITEM, work_in(owner=uuid.uuid4()))

    def test_only_an_administrator_starts_an_initiative(self):
        actor = make_actor(role=RoleType.VP, below=(uuid.uuid4(),))

        assert not can(actor, Action.CREATE_INITIATIVE, member_in())


class TestDelegation:
    def test_delegating_needs_both_the_work_and_the_person(self):
        report = uuid.uuid4()
        actor = make_actor(below=(report,))

        assert can(
            actor,
            Action.DELEGATE_RESPONSIBILITY,
            delegation_in(owner=actor.membership_id, to=report),
        )

    def test_you_cannot_delegate_work_that_is_not_yours(self):
        report = uuid.uuid4()
        actor = make_actor(below=(report,))

        decision = can(
            actor,
            Action.DELEGATE_RESPONSIBILITY,
            delegation_in(owner=uuid.uuid4(), to=report),
        )

        assert not decision
        assert "work you are responsible for" in decision.reason

    def test_you_cannot_delegate_to_someone_outside_your_branch(self):
        actor = make_actor(below=(uuid.uuid4(),))

        decision = can(
            actor,
            Action.DELEGATE_RESPONSIBILITY,
            delegation_in(owner=actor.membership_id, to=uuid.uuid4()),
        )

        assert not decision
        assert "reports to you" in decision.reason

    def test_you_cannot_delegate_to_yourself(self):
        """``manages`` is strict: delegation moves work down, never sideways."""
        actor = make_actor()

        assert not can(
            actor,
            Action.DELEGATE_RESPONSIBILITY,
            delegation_in(owner=actor.membership_id, to=actor.membership_id),
        )

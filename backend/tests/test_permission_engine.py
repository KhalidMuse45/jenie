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
    MemberSubject,
    PermissionDenied,
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
            assert can(actor, action, member_in()), action


class TestFailClosed:
    def test_an_action_without_a_rule_is_denied(self):
        """The engine is closed. New resources add rules; they do not relax this."""
        actor = make_actor()
        unruled = [action for action in Action if action not in _RULES]

        assert unruled, "expected some actions to have no rule yet"
        for action in unruled:
            assert not can(actor, action, member_in()), action

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
            decision = can(actor, action, member_in())
            if decision.allowed:
                continue
            assert decision.reason.endswith("."), decision.reason
            assert decision.reason[0].isupper(), decision.reason
            assert not uuid_like.search(decision.reason), decision.reason

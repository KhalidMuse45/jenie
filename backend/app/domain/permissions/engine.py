"""The permission engine.

Every authorization decision in Jenie is made here. Route handlers, the message
pipeline, and the domain services ask this module; none of them check a role
themselves. A language model never participates -- it can only name an action,
and this decides whether that action is allowed.

``can`` is a pure function. The one fact it needs from the database, the set of
memberships at or below the actor, is resolved once by :mod:`.context` and
carried on the :class:`Actor`.

The engine is closed: an action with no registered rule is denied. Adding a
resource in a later milestone means adding its rule, not relaxing a default.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.enums import MembershipStatus, RoleType
from app.domain.permissions.actions import Action
from app.domain.permissions.subjects import MemberSubject, Subject


class PermissionDenied(Exception):
    """Raised by :func:`require`.

    The message is written for a person and is relayed to users verbatim, so it
    must never contain identifiers or internal state.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is attempting something, and how far their authority reaches.

    ``scope`` is the actor's own membership plus every membership beneath it.
    Holding it as a value keeps the hierarchy out of the rules: "may I act on
    this person" becomes a set membership test.
    """

    membership_id: uuid.UUID
    organization_id: uuid.UUID
    role_type: RoleType
    is_superadmin: bool
    status: MembershipStatus
    scope: frozenset[uuid.UUID]

    def covers(self, membership_id: uuid.UUID) -> bool:
        """The actor is this membership, or somewhere above it."""
        return membership_id in self.scope

    def manages(self, membership_id: uuid.UUID) -> bool:
        """The actor is strictly above this membership."""
        return membership_id != self.membership_id and membership_id in self.scope


Rule = Callable[[Actor, Subject | None], Decision]


def _allow(reason: str) -> Decision:
    return Decision(True, reason)


def _deny(reason: str) -> Decision:
    return Decision(False, reason)


def _expect(subject: Subject | None, kind: type) -> Subject:
    """Guard against a caller pairing an action with the wrong subject.

    This is a programming error rather than a policy outcome, so it raises
    instead of denying. A silent denial here would hide the bug and look like a
    permissions problem to whoever reported it.
    """
    if not isinstance(subject, kind):
        raise TypeError(f"expected {kind.__name__}, got {type(subject).__name__}")
    return subject


def _view_member_work(actor: Actor, subject: Subject | None) -> Decision:
    target = _expect(subject, MemberSubject)
    if actor.covers(target.membership_id):
        return _allow("The member is within your part of the organization.")
    return _deny("You can only see work for yourself and the people who report to you.")


def _superadmin_only(what: str) -> Rule:
    """Deliberately restricted to superadmins.

    Registering these keeps the intent visible. A superadmin is already allowed
    earlier in :func:`can`, so reaching one of these means the actor is not one.
    """

    def rule(actor: Actor, subject: Subject | None) -> Decision:
        return _deny(f"Only an organization administrator can {what}.")

    return rule


_RULES: dict[Action, Rule] = {
    Action.VIEW_MEMBER_WORK: _view_member_work,
    Action.VIEW_ORGANIZATION_WORK: _superadmin_only("see the whole organization's work"),
    Action.MANAGE_MEMBERS: _superadmin_only("add or change members"),
    Action.MANAGE_HIERARCHY: _superadmin_only("change who reports to whom"),
}


def can(actor: Actor, action: Action, subject: Subject | None = None) -> Decision:
    """Decide whether ``actor`` may perform ``action`` on ``subject``."""
    if actor.status is not MembershipStatus.ACTIVE:
        return _deny("Your membership in this organization is not active.")

    # Before the superadmin shortcut: administrator authority stops at the edge
    # of the organization it was granted in.
    if subject is not None and subject.organization_id != actor.organization_id:
        return _deny("That belongs to a different organization.")

    if actor.is_superadmin:
        return _allow("Organization administrators may take any action.")

    rule = _RULES.get(action)
    if rule is None:
        return _deny("That action isn't available to you.")

    return rule(actor, subject)


def require(actor: Actor, action: Action, subject: Subject | None = None) -> None:
    """Authorize or raise :class:`PermissionDenied`."""
    decision = can(actor, action, subject)
    if not decision.allowed:
        raise PermissionDenied(decision.reason)

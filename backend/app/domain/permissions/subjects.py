"""What an action is being attempted *on*.

Subjects are plain values, not ORM rows. The engine stays a pure function of its
inputs, which keeps the policy testable without a database and stops callers
from smuggling lazy-loaded relationships into an authorization decision.

Callers build these from their models. More subject types arrive with the work
tree and delegation plans.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemberSubject:
    """Another membership -- the target of "show me Sarah's work"."""

    organization_id: uuid.UUID
    membership_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class WorkSubject:
    """A work item.

    ``created_by_membership_id`` matters because ownership is optional: an
    initiative can exist before anyone is responsible for it, and until then
    authority follows whoever created it.
    """

    organization_id: uuid.UUID
    work_item_id: uuid.UUID
    owner_membership_id: uuid.UUID | None
    created_by_membership_id: uuid.UUID

    @property
    def responsible_membership_id(self) -> uuid.UUID:
        return self.owner_membership_id or self.created_by_membership_id


@dataclass(frozen=True, slots=True)
class DelegationSubject:
    """Handing a responsibility to someone.

    Two questions at once -- is this work yours to give, and is that person
    yours to give it to -- so both parties travel together.
    """

    organization_id: uuid.UUID
    work_item_id: uuid.UUID
    owner_membership_id: uuid.UUID | None
    created_by_membership_id: uuid.UUID
    proposed_owner_membership_id: uuid.UUID

    @property
    def responsible_membership_id(self) -> uuid.UUID:
        return self.owner_membership_id or self.created_by_membership_id


#: Grows as resources land. Every subject must carry organization_id so the
#: engine can refuse cross-organization access before consulting any rule.
Subject = MemberSubject | WorkSubject | DelegationSubject

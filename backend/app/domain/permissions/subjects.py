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


#: Grows as resources land. Every subject must carry organization_id so the
#: engine can refuse cross-organization access before consulting any rule.
Subject = MemberSubject

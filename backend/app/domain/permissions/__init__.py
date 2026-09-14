"""Authorization.

from app.domain.permissions import Action, can, load_actor, require

actor = await load_actor(session, membership_id)
require(actor, Action.VIEW_MEMBER_WORK, subject_for(sarah))
"""

from app.domain.permissions.actions import Action
from app.domain.permissions.context import (
    load_actor,
    subject_for,
    subject_for_delegation,
    subject_for_plan,
    subject_for_work_item,
)
from app.domain.permissions.engine import (
    Actor,
    Decision,
    PermissionDenied,
    can,
    require,
)
from app.domain.permissions.subjects import (
    DelegationSubject,
    MemberSubject,
    PlanSubject,
    Subject,
    WorkSubject,
)

__all__ = [
    "Action",
    "Actor",
    "Decision",
    "DelegationSubject",
    "MemberSubject",
    "PermissionDenied",
    "PlanSubject",
    "Subject",
    "WorkSubject",
    "can",
    "load_actor",
    "require",
    "subject_for",
    "subject_for_delegation",
    "subject_for_plan",
    "subject_for_work_item",
]

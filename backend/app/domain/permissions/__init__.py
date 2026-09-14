"""Authorization.

from app.domain.permissions import Action, can, load_actor, require

actor = await load_actor(session, membership_id)
require(actor, Action.VIEW_MEMBER_WORK, subject_for(sarah))
"""

from app.domain.permissions.actions import Action
from app.domain.permissions.context import load_actor, subject_for
from app.domain.permissions.engine import (
    Actor,
    Decision,
    PermissionDenied,
    can,
    require,
)
from app.domain.permissions.subjects import MemberSubject, Subject

__all__ = [
    "Action",
    "Actor",
    "Decision",
    "MemberSubject",
    "PermissionDenied",
    "Subject",
    "can",
    "load_actor",
    "require",
    "subject_for",
]

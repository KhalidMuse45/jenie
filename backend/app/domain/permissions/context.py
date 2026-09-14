"""Building an :class:`Actor` from the database.

This is the only part of the permissions package that touches a session. It runs
one hierarchy query per actor; callers handling a single message or request
should load the actor once and reuse it.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Membership
from app.domain.organizations.graph import OrgGraph
from app.domain.permissions.engine import Actor
from app.domain.permissions.subjects import MemberSubject


async def load_actor(session: AsyncSession, membership_id: uuid.UUID) -> Actor | None:
    """Load an actor, or ``None`` when the membership does not exist.

    Returning ``None`` rather than raising lets the message pipeline treat an
    unrecognised sender as an ordinary, answerable situation.
    """
    membership = await session.get(Membership, membership_id)
    if membership is None:
        return None

    scope = await OrgGraph(session).scope_ids(membership.id)

    return Actor(
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role_type=membership.role_type,
        is_superadmin=membership.is_superadmin,
        status=membership.status,
        scope=frozenset(scope),
    )


def subject_for(membership: Membership) -> MemberSubject:
    return MemberSubject(
        organization_id=membership.organization_id,
        membership_id=membership.id,
    )

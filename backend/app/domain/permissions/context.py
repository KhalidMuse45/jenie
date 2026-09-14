"""Building an :class:`Actor` from the database.

This is the only part of the permissions package that touches a session. It runs
one hierarchy query per actor; callers handling a single message or request
should load the actor once and reuse it.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DelegationPlan, Membership, WorkItem
from app.domain.organizations.graph import OrgGraph
from app.domain.permissions.engine import Actor
from app.domain.permissions.subjects import (
    DelegationSubject,
    MemberSubject,
    PlanSubject,
    WorkSubject,
)


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


def subject_for_work_item(work_item: WorkItem) -> WorkSubject:
    return WorkSubject(
        organization_id=work_item.organization_id,
        work_item_id=work_item.id,
        owner_membership_id=work_item.owner_membership_id,
        created_by_membership_id=work_item.created_by_membership_id,
    )


def subject_for_delegation(
    work_item: WorkItem, proposed_owner_membership_id: uuid.UUID
) -> DelegationSubject:
    return DelegationSubject(
        organization_id=work_item.organization_id,
        work_item_id=work_item.id,
        owner_membership_id=work_item.owner_membership_id,
        created_by_membership_id=work_item.created_by_membership_id,
        proposed_owner_membership_id=proposed_owner_membership_id,
    )


def subject_for_plan(plan: DelegationPlan) -> PlanSubject:
    return PlanSubject(
        organization_id=plan.organization_id,
        plan_id=plan.id,
        created_by_membership_id=plan.created_by_membership_id,
        required_approver_membership_id=plan.required_approver_membership_id,
        status=plan.status,
    )

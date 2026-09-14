"""Database-level guarantees about the membership table."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models import Membership
from app.domain.enums import RoleType
from tests.factories import make_member, make_organization


async def test_root_membership_may_have_no_manager(session):
    organization = await make_organization(session)
    president = await make_member(
        session, organization, "president", role=RoleType.PRESIDENT, is_superadmin=True
    )

    assert president.manager_membership_id is None
    assert president.is_superadmin is True


async def test_membership_cannot_manage_itself(session):
    organization = await make_organization(session)
    member = await make_member(session, organization, "solo")

    member.manager_membership_id = member.id

    with pytest.raises(IntegrityError, match="manager_is_not_self"):
        await session.flush()


async def test_manager_must_belong_to_the_same_organization(session):
    """The composite foreign key is the only thing preventing this.

    A single-column reference to memberships.id would happily accept a manager
    from another organization, which would leak authority across tenants.
    """
    org_one = await make_organization(session, "One")
    org_two = await make_organization(session, "Two")

    outsider = await make_member(session, org_two, "outsider")

    session.add(
        Membership(
            organization_id=org_one.id,
            user_id=outsider.user_id,
            title="Impostor",
            role_type=RoleType.MEMBER,
            manager_membership_id=outsider.id,
        )
    )

    with pytest.raises(IntegrityError, match="manager_same_organization"):
        await session.flush()


async def test_a_user_holds_at_most_one_membership_per_organization(session):
    organization = await make_organization(session)
    existing = await make_member(session, organization, "member")

    session.add(
        Membership(
            organization_id=organization.id,
            user_id=existing.user_id,
            title="Second seat",
            role_type=RoleType.LEAD,
        )
    )

    with pytest.raises(IntegrityError, match="organization_id_user_id"):
        await session.flush()


async def test_the_same_user_may_join_two_organizations(session):
    org_one = await make_organization(session, "One")
    org_two = await make_organization(session, "Two")

    first = await make_member(session, org_one, "khalid", role=RoleType.PRESIDENT)

    second = Membership(
        organization_id=org_two.id,
        user_id=first.user_id,
        title="Member",
        role_type=RoleType.MEMBER,
    )
    session.add(second)
    await session.flush()

    assert second.user_id == first.user_id
    assert second.organization_id != first.organization_id

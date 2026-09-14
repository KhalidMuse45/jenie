"""Helpers for building organization fixtures in tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Membership, Organization, User, WorkItem
from app.domain.enums import MembershipStatus, RoleType, WorkItemType
from app.domain.work import create_work_item


async def make_organization(session: AsyncSession, name: str = "Test Org") -> Organization:
    organization = Organization(name=name, timezone="America/Chicago")
    session.add(organization)
    await session.flush()
    return organization


async def make_member(
    session: AsyncSession,
    organization: Organization,
    name: str,
    *,
    manager: Membership | None = None,
    role: RoleType = RoleType.MEMBER,
    title: str | None = None,
    is_superadmin: bool = False,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> Membership:
    user = User(display_name=name)
    session.add(user)
    await session.flush()

    membership = Membership(
        organization_id=organization.id,
        user_id=user.id,
        title=title or name,
        role_type=role,
        manager_membership_id=manager.id if manager else None,
        is_superadmin=is_superadmin,
        status=status,
    )
    session.add(membership)
    await session.flush()
    return membership


async def make_tree(session: AsyncSession) -> dict[str, Membership]:
    """A three-level organization with two branches.

    president
    |- vp_a
    |   |- lead_a
    |   |   `- member_a
    |   `- member_b
    `- vp_b
        `- member_c
    """
    organization = await make_organization(session)

    president = await make_member(
        session, organization, "president", role=RoleType.PRESIDENT, is_superadmin=True
    )
    vp_a = await make_member(session, organization, "vp_a", manager=president, role=RoleType.VP)
    vp_b = await make_member(session, organization, "vp_b", manager=president, role=RoleType.VP)
    lead_a = await make_member(session, organization, "lead_a", manager=vp_a, role=RoleType.LEAD)
    member_a = await make_member(session, organization, "member_a", manager=lead_a)
    member_b = await make_member(session, organization, "member_b", manager=vp_a)
    member_c = await make_member(session, organization, "member_c", manager=vp_b)

    return {
        "organization": organization,
        "president": president,
        "vp_a": vp_a,
        "vp_b": vp_b,
        "lead_a": lead_a,
        "member_a": member_a,
        "member_b": member_b,
        "member_c": member_c,
    }


async def make_initiative(
    session: AsyncSession,
    organization: Organization,
    creator: Membership,
    *,
    title: str = "Google AI Workshop",
    owner: Membership | None = None,
) -> WorkItem:
    return await create_work_item(
        session,
        organization_id=organization.id,
        item_type=WorkItemType.INITIATIVE,
        title=title,
        created_by_membership_id=creator.id,
        owner_membership_id=owner.id if owner else None,
    )


async def make_child(
    session: AsyncSession,
    parent: WorkItem,
    creator: Membership,
    *,
    item_type: WorkItemType,
    title: str,
    owner: Membership | None = None,
) -> WorkItem:
    return await create_work_item(
        session,
        organization_id=parent.organization_id,
        item_type=item_type,
        title=title,
        created_by_membership_id=creator.id,
        parent=parent,
        owner_membership_id=owner.id if owner else None,
    )

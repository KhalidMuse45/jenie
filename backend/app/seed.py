"""Seed a development organization.

Run with ``uv run python -m app.seed``. Safe to run repeatedly: identifiers are
derived from a fixed namespace with uuid5, so a second run finds the rows it
would have created and leaves them alone. That also means JENIE_DEFAULT_ORG_ID
stays stable across rebuilds of the database.

This is development data. Production members arrive through the enrollment flow.
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Membership, Organization, User
from app.database.session import get_engine, get_sessionmaker
from app.domain.enums import MembershipStatus, RoleType

# Arbitrary but fixed. Changing it produces an entirely new set of seed rows.
NAMESPACE = uuid.UUID("1f6d9d3c-6a4e-5a2b-9c3d-2f8b7a1e4c50")

ORG_SLUG = "colorstack-umn"
ORG_NAME = "ColorStack UMN"
ORG_TIMEZONE = "America/Chicago"

# (key, display name, title, role, manager key, superadmin)
PEOPLE: list[tuple[str, str, str, RoleType, str | None, bool]] = [
    ("khalid", "Khalid", "President", RoleType.PRESIDENT, None, True),
    ("sarah", "Sarah", "VP External", RoleType.VP, "khalid", False),
    ("izra", "Izra", "Marketing Member", RoleType.MEMBER, "sarah", False),
    ("marwa", "Marwa", "Marketing Member", RoleType.MEMBER, "sarah", False),
]


def stable_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, ":".join(parts))


async def seed(session: AsyncSession) -> Organization:
    org_id = stable_id("organization", ORG_SLUG)

    organization = await session.get(Organization, org_id)
    if organization is None:
        organization = Organization(id=org_id, name=ORG_NAME, timezone=ORG_TIMEZONE)
        session.add(organization)
        await session.flush()

    # Managers must exist before their reports: the manager reference is a real
    # foreign key, checked on insert rather than at commit. PEOPLE is ordered
    # top-down for that reason.
    memberships: dict[str, Membership] = {}

    for key, display_name, title, role, manager_key, is_superadmin in PEOPLE:
        user_id = stable_id("user", ORG_SLUG, key)
        user = await session.get(User, user_id)
        if user is None:
            user = User(id=user_id, display_name=display_name)
            session.add(user)
            await session.flush()

        membership_id = stable_id("membership", ORG_SLUG, key)
        membership = await session.get(Membership, membership_id)
        if membership is None:
            membership = Membership(
                id=membership_id,
                organization_id=organization.id,
                user_id=user.id,
                title=title,
                role_type=role,
                manager_membership_id=(
                    memberships[manager_key].id if manager_key is not None else None
                ),
                is_superadmin=is_superadmin,
                status=MembershipStatus.ACTIVE,
            )
            session.add(membership)
            await session.flush()

        memberships[key] = membership

    return organization


async def main() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        organization = await seed(session)
        await session.commit()
        org_id = organization.id

    await get_engine().dispose()

    print(f"Seeded {ORG_NAME}")
    print(f"JENIE_DEFAULT_ORG_ID={org_id}")


if __name__ == "__main__":
    asyncio.run(main())

"""The development seed."""

from sqlalchemy import func, select

from app.database.models import Membership, MessagingIdentity, Organization, User
from app.domain.enums import MessagingChannel
from app.domain.identity import resolve_sender
from app.domain.organizations.graph import OrgGraph
from app.seed import ORG_NAME, seed, stable_id


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_seed_creates_the_development_organization(session):
    organization = await seed(session)

    assert organization.name == ORG_NAME
    assert await _count(session, Organization) == 1
    assert await _count(session, User) == 4
    assert await _count(session, Membership) == 4


async def test_seed_is_idempotent(session):
    first = await seed(session)
    second = await seed(session)

    assert first.id == second.id
    assert await _count(session, Membership) == 4


async def test_seed_identifiers_are_stable(session):
    """A rebuilt database keeps the same JENIE_DEFAULT_ORG_ID."""
    organization = await seed(session)

    assert organization.id == stable_id("organization", "colorstack-umn")


async def test_seeded_hierarchy_matches_the_documented_shape(session):
    await seed(session)
    graph = OrgGraph(session)

    khalid = await session.get(Membership, stable_id("membership", "colorstack-umn", "khalid"))
    sarah = await session.get(Membership, stable_id("membership", "colorstack-umn", "sarah"))
    izra = await session.get(Membership, stable_id("membership", "colorstack-umn", "izra"))

    assert khalid.is_superadmin is True
    assert khalid.manager_membership_id is None

    # Khalid sees the whole organization; Sarah sees only her two reports.
    assert len(await graph.descendants(khalid.id)) == 3
    assert len(await graph.descendants(sarah.id)) == 2

    assert await graph.is_ancestor(khalid.id, izra.id) is True
    assert await graph.is_ancestor(izra.id, khalid.id) is False


async def test_seed_registers_a_verified_identity_for_everyone(session):
    await seed(session)

    assert await _count(session, MessagingIdentity) == 4


async def test_seeded_members_resolve_from_their_addresses(session):
    """The seed writes addresses the way people type them.

    Each must survive normalisation and come back as the right person.
    """
    organization = await seed(session)

    for address, expected in [
        ("6125550101", "Khalid"),
        ("+1 (612) 555-0102", "Sarah"),
        ("612.555.0103", "Izra"),
        ("MARWA@EXAMPLE.COM", "Marwa"),
    ]:
        member = await resolve_sender(
            session,
            channel=MessagingChannel.IMESSAGE,
            address=address,
            organization_id=organization.id,
        )
        assert member is not None, address
        user = await session.get(User, member.user_id)
        assert user.display_name == expected, address


async def test_seeding_twice_does_not_duplicate_identities(session):
    await seed(session)
    await seed(session)

    assert await _count(session, MessagingIdentity) == 4

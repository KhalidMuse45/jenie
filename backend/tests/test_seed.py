"""The development seed."""

from sqlalchemy import func, select

from app.database.models import Membership, Organization, User
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

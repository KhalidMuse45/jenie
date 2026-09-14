"""Hierarchy traversal."""

import asyncio

import pytest

from app.domain.organizations.graph import OrgGraph
from tests.factories import make_member, make_organization, make_tree


async def test_descendants_reach_every_level_with_distance(session):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    found = {rel.membership_id: rel.depth for rel in await graph.descendants(tree["president"].id)}

    assert found == {
        tree["vp_a"].id: 1,
        tree["vp_b"].id: 1,
        tree["lead_a"].id: 2,
        tree["member_b"].id: 2,
        tree["member_c"].id: 2,
        tree["member_a"].id: 3,
    }


async def test_descendants_exclude_the_membership_itself(session):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    found = [rel.membership_id for rel in await graph.descendants(tree["vp_a"].id)]

    assert tree["vp_a"].id not in found
    assert set(found) == {tree["lead_a"].id, tree["member_b"].id, tree["member_a"].id}


async def test_descendants_of_a_leaf_are_empty(session):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    assert await graph.descendants(tree["member_a"].id) == []


async def test_a_branch_cannot_see_a_sibling_branch(session):
    """VP A's scope must not contain anything under VP B.

    This is the structural fact the permission engine relies on to keep one
    vice president out of another's work.
    """
    tree = await make_tree(session)
    graph = OrgGraph(session)

    scope = await graph.scope_ids(tree["vp_a"].id)

    assert tree["vp_a"].id in scope
    assert tree["member_c"].id not in scope
    assert tree["vp_b"].id not in scope


async def test_ancestors_are_ordered_nearest_first(session):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    chain = await graph.ancestors(tree["member_a"].id)

    assert [rel.membership_id for rel in chain] == [
        tree["lead_a"].id,
        tree["vp_a"].id,
        tree["president"].id,
    ]
    assert [rel.depth for rel in chain] == [1, 2, 3]


async def test_the_root_has_no_ancestors(session):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    assert await graph.ancestors(tree["president"].id) == []


async def test_direct_reports_are_one_level_only(session):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    reports = set(await graph.direct_reports(tree["vp_a"].id))

    assert reports == {tree["lead_a"].id, tree["member_b"].id}
    assert tree["member_a"].id not in reports


@pytest.mark.parametrize(
    ("ancestor", "descendant", "expected"),
    [
        ("president", "member_a", True),
        ("vp_a", "member_a", True),
        ("lead_a", "member_a", True),
        ("vp_b", "member_a", False),
        ("member_a", "president", False),
        ("member_a", "member_a", False),
    ],
)
async def test_is_ancestor(session, ancestor, descendant, expected):
    tree = await make_tree(session)
    graph = OrgGraph(session)

    assert await graph.is_ancestor(tree[ancestor].id, tree[descendant].id) is expected


async def test_a_cycle_terminates_instead_of_hanging(session):
    """A manager loop must not turn a traversal into an infinite query.

    Nothing in the schema prevents a cycle -- the only guard is the path array
    in the recursive CTE. Without it these calls never return, so the timeout
    here is the actual assertion.
    """
    organization = await make_organization(session)
    first = await make_member(session, organization, "first")
    second = await make_member(session, organization, "second", manager=first)

    first.manager_membership_id = second.id
    await session.flush()

    graph = OrgGraph(session)

    descendants = await asyncio.wait_for(graph.descendants(first.id), timeout=10)
    ancestors = await asyncio.wait_for(graph.ancestors(first.id), timeout=10)

    assert [rel.membership_id for rel in descendants] == [second.id]
    assert [rel.membership_id for rel in ancestors] == [second.id]


async def test_traversal_does_not_cross_organizations(session):
    org_one = await make_organization(session, "One")
    org_two = await make_organization(session, "Two")

    president = await make_member(session, org_one, "president")
    await make_member(session, org_one, "report", manager=president)
    stranger = await make_member(session, org_two, "stranger")

    graph = OrgGraph(session)
    scope = await graph.scope_ids(president.id)

    assert stranger.id not in scope

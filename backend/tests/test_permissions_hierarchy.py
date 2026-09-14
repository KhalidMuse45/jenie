"""Milestone 1 acceptance: the engine against a real organization tree."""

import uuid

from app.domain.enums import MembershipStatus, RoleType
from app.domain.permissions import (
    Action,
    can,
    load_actor,
    subject_for,
)
from tests.factories import make_member, make_organization, make_tree


async def test_the_president_sees_everyone(session):
    tree = await make_tree(session)
    president = await load_actor(session, tree["president"].id)

    for key in ("vp_a", "vp_b", "lead_a", "member_a", "member_b", "member_c"):
        assert can(president, Action.VIEW_MEMBER_WORK, subject_for(tree[key])), key


async def test_a_vice_president_sees_their_own_branch(session):
    tree = await make_tree(session)
    vp = await load_actor(session, tree["vp_a"].id)

    for key in ("vp_a", "lead_a", "member_a", "member_b"):
        assert can(vp, Action.VIEW_MEMBER_WORK, subject_for(tree[key])), key


async def test_a_vice_president_cannot_reach_another_branch(session):
    tree = await make_tree(session)
    vp = await load_actor(session, tree["vp_a"].id)

    assert not can(vp, Action.VIEW_MEMBER_WORK, subject_for(tree["vp_b"]))
    assert not can(vp, Action.VIEW_MEMBER_WORK, subject_for(tree["member_c"]))


async def test_a_vice_president_cannot_look_upward(session):
    tree = await make_tree(session)
    vp = await load_actor(session, tree["vp_a"].id)

    assert not can(vp, Action.VIEW_MEMBER_WORK, subject_for(tree["president"]))


async def test_a_member_sees_only_themselves(session):
    tree = await make_tree(session)
    member = await load_actor(session, tree["member_a"].id)

    assert can(member, Action.VIEW_MEMBER_WORK, subject_for(tree["member_a"]))

    for key in ("president", "vp_a", "vp_b", "lead_a", "member_b", "member_c"):
        assert not can(member, Action.VIEW_MEMBER_WORK, subject_for(tree[key])), key


async def test_the_president_holds_superadmin_authority(session):
    tree = await make_tree(session)
    president = await load_actor(session, tree["president"].id)

    assert president.is_superadmin is True

    for action in Action:
        assert can(president, action, subject_for(tree["member_c"])), action


async def test_a_vice_president_does_not_hold_superadmin_authority(session):
    tree = await make_tree(session)
    vp = await load_actor(session, tree["vp_a"].id)

    assert not can(vp, Action.MANAGE_HIERARCHY, subject_for(tree["member_a"]))
    assert not can(vp, Action.MANAGE_MEMBERS, subject_for(tree["member_a"]))
    assert not can(vp, Action.VIEW_ORGANIZATION_WORK, subject_for(tree["member_a"]))


async def test_authority_does_not_cross_organizations(session):
    """Even a superadmin is confined to the organization that granted the seat."""
    tree = await make_tree(session)
    other_org = await make_organization(session, "Other")
    stranger = await make_member(session, other_org, "stranger")

    president = await load_actor(session, tree["president"].id)

    assert not can(president, Action.VIEW_MEMBER_WORK, subject_for(stranger))


async def test_an_inactive_membership_loses_its_authority(session):
    organization = await make_organization(session)
    president = await make_member(
        session,
        organization,
        "president",
        role=RoleType.PRESIDENT,
        is_superadmin=True,
        status=MembershipStatus.INACTIVE,
    )
    member = await make_member(session, organization, "member", manager=president)

    actor = await load_actor(session, president.id)

    assert not can(actor, Action.VIEW_MEMBER_WORK, subject_for(member))


async def test_the_actor_scope_matches_the_hierarchy(session):
    tree = await make_tree(session)

    vp = await load_actor(session, tree["vp_a"].id)

    assert vp.scope == {
        tree["vp_a"].id,
        tree["lead_a"].id,
        tree["member_a"].id,
        tree["member_b"].id,
    }
    assert vp.manages(tree["member_a"].id) is True
    assert vp.manages(tree["vp_a"].id) is False
    assert vp.covers(tree["vp_a"].id) is True


async def test_an_unknown_membership_has_no_actor(session):
    await make_tree(session)

    assert await load_actor(session, uuid.uuid4()) is None

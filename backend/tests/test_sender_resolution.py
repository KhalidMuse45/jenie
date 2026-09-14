"""Turning an incoming address into a person."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import MembershipStatus, MessagingChannel
from app.domain.identity import InvalidAddress, register_identity, resolve_sender
from tests.factories import make_member, make_organization

IMESSAGE = MessagingChannel.IMESSAGE


async def _member_with_address(session, organization, name, address, *, verified=True, **kwargs):
    member = await make_member(session, organization, name, **kwargs)
    await register_identity(
        session,
        user_id=member.user_id,
        channel=IMESSAGE,
        address=address,
        verified=verified,
    )
    return member


@pytest.mark.parametrize(
    "incoming",
    ["+16125550101", "6125550101", "(612) 555-0101", "612-555-0101", "tel:+16125550101"],
)
async def test_any_formatting_of_a_known_number_resolves(session, incoming):
    organization = await make_organization(session)
    khalid = await _member_with_address(session, organization, "khalid", "(612) 555-0101")

    found = await resolve_sender(
        session, channel=IMESSAGE, address=incoming, organization_id=organization.id
    )

    assert found is not None
    assert found.id == khalid.id


async def test_an_email_address_resolves_case_insensitively(session):
    organization = await make_organization(session)
    marwa = await _member_with_address(session, organization, "marwa", "Marwa@Example.com")

    found = await resolve_sender(
        session, channel=IMESSAGE, address="MARWA@example.COM", organization_id=organization.id
    )

    assert found.id == marwa.id


async def test_an_unverified_identity_does_not_resolve(session):
    """An unverified row is an unchecked claim.

    Honouring it would let anyone who knows a member's address text Jenie and be
    treated as that member.
    """
    organization = await make_organization(session)
    await _member_with_address(session, organization, "impostor", "+16125550199", verified=False)

    found = await resolve_sender(
        session, channel=IMESSAGE, address="+16125550199", organization_id=organization.id
    )

    assert found is None


async def test_an_inactive_membership_still_resolves(session):
    """Resolution is identity, not authorization.

    The permission engine refuses them with a reason they can act on, which
    beats Jenie claiming not to know who they are.
    """
    organization = await make_organization(session)
    former = await _member_with_address(
        session,
        organization,
        "former",
        "+16125550188",
        status=MembershipStatus.INACTIVE,
    )

    found = await resolve_sender(
        session, channel=IMESSAGE, address="+16125550188", organization_id=organization.id
    )

    assert found.id == former.id
    assert found.status is MembershipStatus.INACTIVE


async def test_an_unknown_address_resolves_to_nobody(session):
    organization = await make_organization(session)
    await _member_with_address(session, organization, "khalid", "+16125550101")

    assert (
        await resolve_sender(
            session, channel=IMESSAGE, address="+16125559999", organization_id=organization.id
        )
        is None
    )


async def test_an_unparseable_address_resolves_to_nobody_without_raising(session):
    """A malformed webhook must not take the pipeline down."""
    organization = await make_organization(session)

    assert (
        await resolve_sender(
            session, channel=IMESSAGE, address="garbage", organization_id=organization.id
        )
        is None
    )


async def test_resolution_is_scoped_to_one_organization(session):
    organization = await make_organization(session, "One")
    other = await make_organization(session, "Two")
    await _member_with_address(session, other, "outsider", "+16125550177")

    assert (
        await resolve_sender(
            session, channel=IMESSAGE, address="+16125550177", organization_id=organization.id
        )
        is None
    )


async def test_the_channel_is_part_of_the_identity(session):
    """The same number over SMS is a different identity, and must not resolve."""
    organization = await make_organization(session)
    await _member_with_address(session, organization, "khalid", "+16125550101")

    assert (
        await resolve_sender(
            session,
            channel=MessagingChannel.SMS,
            address="+16125550101",
            organization_id=organization.id,
        )
        is None
    )


async def test_one_address_cannot_belong_to_two_people_on_a_channel(session):
    organization = await make_organization(session)
    await _member_with_address(session, organization, "first", "+16125550101")
    second = await make_member(session, organization, "second")

    with pytest.raises(IntegrityError, match="channel_address_norm"):
        await register_identity(
            session,
            user_id=second.user_id,
            channel=IMESSAGE,
            # Written differently, but the same address once normalised.
            address="(612) 555-0101",
            verified=True,
        )


async def test_the_same_address_may_exist_on_two_channels(session):
    organization = await make_organization(session)
    member = await make_member(session, organization, "khalid")

    await register_identity(
        session, user_id=member.user_id, channel=IMESSAGE, address="+16125550101", verified=True
    )
    sms = await register_identity(
        session,
        user_id=member.user_id,
        channel=MessagingChannel.SMS,
        address="+16125550101",
        verified=True,
    )

    assert sms.address_norm == "+16125550101"


async def test_an_unusable_address_is_refused_at_enrolment(session):
    """Better to fail here than to store a row that can never match."""
    organization = await make_organization(session)
    member = await make_member(session, organization, "khalid")

    with pytest.raises(InvalidAddress):
        await register_identity(
            session, user_id=member.user_id, channel=IMESSAGE, address="nonsense", verified=True
        )


async def test_registering_keeps_the_original_spelling(session):
    organization = await make_organization(session)
    member = await make_member(session, organization, "khalid")

    identity = await register_identity(
        session, user_id=member.user_id, channel=IMESSAGE, address="(612) 555-0101", verified=True
    )

    assert identity.address_raw == "(612) 555-0101"
    assert identity.address_norm == "+16125550101"
    assert identity.verified_at is not None

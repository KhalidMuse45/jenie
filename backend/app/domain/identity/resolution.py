"""Turning an incoming address into the person who sent it.

    sender address -> MessagingIdentity -> User -> Membership -> permissions

Every step is required. A message that cannot be walked all the way to a
membership is from a stranger, and Jenie treats it as such.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Membership, MessagingIdentity
from app.domain.enums import MessagingChannel
from app.domain.identity.addresses import InvalidAddress, normalize_address


async def resolve_sender(
    session: AsyncSession,
    *,
    channel: MessagingChannel,
    address: str,
    organization_id: uuid.UUID,
) -> Membership | None:
    """Find the membership behind ``address``, or ``None``.

    Only **verified** identities resolve. An unverified row is a claim that
    nobody has checked, and acting on it would let anyone who knows a member's
    name text Jenie and be treated as that member.

    Inactive memberships *do* resolve. The permission engine then refuses them
    with "your membership is not active", which is a far more useful reply than
    pretending not to know who they are.
    """
    try:
        canonical = normalize_address(address)
    except InvalidAddress:
        return None

    return await session.scalar(
        select(Membership)
        .join(MessagingIdentity, MessagingIdentity.user_id == Membership.user_id)
        .where(
            MessagingIdentity.channel == channel,
            MessagingIdentity.address_norm == canonical,
            MessagingIdentity.verified.is_(True),
            Membership.organization_id == organization_id,
        )
    )


async def register_identity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel: MessagingChannel,
    address: str,
    verified: bool = False,
) -> MessagingIdentity:
    """Attach an address to a user.

    The single place addresses are written, so a value can never reach
    ``address_norm`` without going through normalisation first. Raises
    :class:`InvalidAddress` if the address cannot be canonicalised -- better to
    refuse at enrolment than to store a row that will never match anything.
    """
    canonical = normalize_address(address)

    identity = MessagingIdentity(
        user_id=user_id,
        channel=channel,
        address_raw=address,
        address_norm=canonical,
        verified=verified,
        verified_at=datetime.now(UTC) if verified else None,
    )
    session.add(identity)
    await session.flush()
    return identity

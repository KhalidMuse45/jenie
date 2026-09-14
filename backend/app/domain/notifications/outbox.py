"""Queueing outbound messages.

Called from inside the transaction that causes the notification. Nothing here
talks to a network.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Membership, MessagingIdentity, OutboundMessage
from app.domain.enums import (
    MessagingChannel,
    OutboundMessageStatus,
    OutboundMessageType,
)


async def enqueue(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    recipient_membership_id: uuid.UUID,
    message_type: OutboundMessageType,
    body: str,
    channel: MessagingChannel = MessagingChannel.IMESSAGE,
    now: datetime | None = None,
) -> OutboundMessage:
    """Queue one message for later delivery.

    A recipient with no verified address still gets a row, marked FAILED. The
    alternative -- skipping them -- makes "nobody told Marwa" invisible, and the
    count of notifications silently stop matching the count of assignments.
    """
    destination = await _destination_for(session, recipient_membership_id, channel)

    message = OutboundMessage(
        organization_id=organization_id,
        recipient_membership_id=recipient_membership_id,
        channel=channel,
        destination=destination,
        message_type=message_type,
        body=body,
        status=(OutboundMessageStatus.PENDING if destination else OutboundMessageStatus.FAILED),
        last_error=None if destination else "No verified messaging identity for this member.",
    )
    if now is not None:
        message.available_at = now
        message.created_at = now

    session.add(message)
    await session.flush()
    return message


async def _destination_for(
    session: AsyncSession, membership_id: uuid.UUID, channel: MessagingChannel
) -> str | None:
    return await session.scalar(
        select(MessagingIdentity.address_norm)
        .join(Membership, Membership.user_id == MessagingIdentity.user_id)
        .where(
            Membership.id == membership_id,
            MessagingIdentity.channel == channel,
            MessagingIdentity.verified.is_(True),
        )
        .limit(1)
    )

"""Queued outbound messages.

Notifications are rows written inside the transaction that caused them, not HTTP
calls made during it. Approving a plan and telling five people about it either
both happen or neither does; a worker delivers them afterwards.

Sending inside the transaction would mean a failure at message four leaves three
people told about work that then gets rolled back.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base
from app.database.models.mixins import UUIDPrimaryKeyMixin
from app.domain.enums import MessagingChannel, OutboundMessageStatus, OutboundMessageType


class OutboundMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outbound_messages"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    recipient_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    channel: Mapped[MessagingChannel] = mapped_column(
        Enum(MessagingChannel, native_enum=False, length=20), nullable=False
    )

    # Null only when the recipient has no verified address. The row is still
    # written, as FAILED, so that "nobody told Marwa" is visible rather than a
    # silent gap between assignments and notifications.
    destination: Mapped[str | None] = mapped_column(String(320), nullable=True)

    message_type: Mapped[OutboundMessageType] = mapped_column(
        Enum(OutboundMessageType, native_enum=False, length=30), nullable=False
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[OutboundMessageStatus] = mapped_column(
        Enum(OutboundMessageStatus, native_enum=False, length=20),
        nullable=False,
        server_default=text(f"'{OutboundMessageStatus.PENDING.value}'"),
    )

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # When a worker may next pick this up. Retries push it forward.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["recipient_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_outbound_messages_recipient_same_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "destination IS NOT NULL OR status = 'FAILED'",
            name="undeliverable_rows_are_marked_failed",
        ),
        # The worker's claim query: pending rows that are due, oldest first.
        Index("ix_outbound_messages_status_available_at", "status", "available_at"),
        Index("ix_outbound_messages_organization_id", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<OutboundMessage {self.message_type} {self.status}>"

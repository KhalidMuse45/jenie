"""Messaging identities.

A message carries an address, not a name. Nothing a sender writes about who they
are is trusted -- the address is matched against a verified identity, and that
is the only way a message becomes attributable to a person.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import MessagingChannel


class MessagingIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messaging_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    channel: Mapped[MessagingChannel] = mapped_column(
        Enum(MessagingChannel, native_enum=False, length=20), nullable=False
    )

    # As it arrived, kept only for debugging a failed match.
    address_raw: Mapped[str] = mapped_column(String(320), nullable=False)

    # The canonical form. Every lookup goes through this column; the deliberate
    # asymmetry in the two names is there so that querying with an unnormalised
    # value looks wrong at the call site.
    address_norm: Mapped[str] = mapped_column(String(320), nullable=False)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["object"] = relationship("User", lazy="raise")

    __table_args__ = (
        # One address belongs to one person per channel. The same phone number
        # reaching Jenie over iMessage and over SMS is two identities.
        UniqueConstraint(
            "channel", "address_norm", name="uq_messaging_identities_channel_address_norm"
        ),
        CheckConstraint(
            "verified = false OR verified_at IS NOT NULL",
            name="verified_records_when",
        ),
    )

    def __repr__(self) -> str:
        return f"<MessagingIdentity {self.channel} {self.address_norm!r}>"

"""Organization, user, and membership tables.

A person is a ``User``. Their position inside a particular organization is a
``Membership``. Authority is always evaluated against a membership, never a
user, so that one person can eventually belong to several organizations without
carrying permissions between them.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import MembershipStatus, RoleType


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # IANA zone. Relative dates in messages ("Thursday") are resolved against
    # this before being stored as UTC.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'America/Chicago'")
    )

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False)

    role_type: Mapped[RoleType] = mapped_column(
        Enum(RoleType, native_enum=False, length=20), nullable=False
    )

    # No plain ForeignKey here: the composite constraint below ties the manager
    # to the same organization, which a single-column reference cannot express.
    manager_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, length=20),
        nullable=False,
        server_default=text(f"'{MembershipStatus.ACTIVE.value}'"),
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_memberships_organization_id_user_id"
        ),
        # Target for the composite manager reference below.
        UniqueConstraint("id", "organization_id", name="uq_memberships_id_organization_id"),
        # A manager must be a membership in the same organization. MATCH SIMPLE
        # means the constraint is skipped when manager_membership_id is NULL,
        # which is what lets the root of the tree exist.
        #
        # RESTRICT, not SET NULL: nulling the manager would have to null
        # organization_id too, which is NOT NULL. Reassign someone's reports
        # before removing them.
        ForeignKeyConstraint(
            ["manager_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_memberships_manager_same_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "manager_membership_id IS NULL OR manager_membership_id <> id",
            name="manager_is_not_self",
        ),
        Index("ix_memberships_organization_id", "organization_id"),
        # Supports the recursive descendant walk, which joins on this column.
        Index("ix_memberships_manager_membership_id", "manager_membership_id"),
    )

    def __repr__(self) -> str:
        return f"<Membership {self.title!r} id={self.id}>"

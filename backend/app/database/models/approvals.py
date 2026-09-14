"""Approval records and the organization audit log.

An approval is not a boolean on the plan. It is a row naming who decided, what
they decided, and -- critically -- *which version* of the plan they were looking
at when they decided it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base
from app.database.models.mixins import UUIDPrimaryKeyMixin
from app.domain.enums import ApprovalDecision, AuditAction


class Approval(UUIDPrimaryKeyMixin, Base):
    """One decision on one plan. Append-only."""

    __tablename__ = "approvals"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("delegation_plans.id", ondelete="CASCADE"), nullable=False
    )

    # The version the approver actually read. An edit that lands between
    # "here is the plan" and "approve" moves the version, so the record shows
    # what was agreed to rather than what the plan later became.
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)

    approver_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=False
    )

    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, native_enum=False, length=20), nullable=False
    )

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # A plan can be approved once. The status check inside the row lock is
        # the first line of defence; this is the one that cannot be raced.
        Index(
            "uq_approvals_one_approval_per_plan",
            "plan_id",
            unique=True,
            postgresql_where=text("decision = 'APPROVED'"),
        ),
        Index("ix_approvals_plan_id", "plan_id"),
    )

    def __repr__(self) -> str:
        return f"<Approval {self.decision} plan={self.plan_id} v{self.plan_version}>"


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Organization-wide history of consequential actions."""

    __tablename__ = "audit_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    # Null when Jenie itself acted.
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, native_enum=False, length=40), nullable=False
    )

    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    before_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    after_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # ``metadata`` is taken by SQLAlchemy's declarative base.
    payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_audit_events_actor_same_organization",
            ondelete="SET NULL",
        ),
        Index("ix_audit_events_organization_id", "organization_id"),
        Index("ix_audit_events_target_id", "target_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.action} {self.target_type}={self.target_id}>"

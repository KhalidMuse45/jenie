"""Delegation plans.

A plan is a *proposal*. Its items look like tasks and read like tasks, but
nothing in them exists as real work until an approver says so. That separation
is the whole point of Jenie: a manager can think out loud about who should do
what without anybody's phone lighting up.

Once approved, a plan becomes history and stops being editable.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import DelegationPlanStatus, WorkItemType


class DelegationPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "delegation_plans"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    # The responsibility this plan breaks down.
    scope_work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_by_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Decided when the plan is submitted, not when it is created: a draft has
    # not been sent to anyone yet.
    required_approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    status: Mapped[DelegationPlanStatus] = mapped_column(
        Enum(DelegationPlanStatus, native_enum=False, length=20),
        nullable=False,
        server_default=text(f"'{DelegationPlanStatus.DRAFT.value}'"),
    )

    short_code: Mapped[str] = mapped_column(String(16), nullable=False)

    # Bumped by every edit. An approval names the version it approved, so an
    # edit that lands between "here is the plan" and "approve" cannot be
    # mistaken for agreement to the new text.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["DelegationPlanItem"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="DelegationPlanItem.sort_order",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_delegation_plans_id_organization_id"),
        UniqueConstraint(
            "organization_id", "short_code", name="uq_delegation_plans_organization_id_short_code"
        ),
        ForeignKeyConstraint(
            ["scope_work_item_id", "organization_id"],
            ["work_items.id", "work_items.organization_id"],
            name="fk_delegation_plans_scope_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_delegation_plans_creator_same_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["required_approver_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_delegation_plans_approver_same_organization",
            ondelete="RESTRICT",
        ),
        # A plan that has left DRAFT was sent to someone, at a known moment.
        CheckConstraint(
            "status = 'DRAFT' OR required_approver_membership_id IS NOT NULL",
            name="submitted_plans_have_an_approver",
        ),
        CheckConstraint(
            "status = 'DRAFT' OR submitted_at IS NOT NULL",
            name="submitted_plans_record_when",
        ),
        CheckConstraint(
            "(status = 'APPROVED') = (approved_at IS NOT NULL)",
            name="approved_at_matches_status",
        ),
        # At most one plan in flight per responsibility. Two open plans for
        # "Marketing" makes "approve Sarah's plan" ambiguous, and ambiguity in a
        # state-changing request is the one thing Jenie must never resolve by
        # guessing. A rejected plan frees the slot for a revision.
        Index(
            "uq_delegation_plans_one_open_per_scope",
            "scope_work_item_id",
            unique=True,
            postgresql_where=text("status IN ('DRAFT', 'PENDING_APPROVAL')"),
        ),
        Index("ix_delegation_plans_organization_id", "organization_id"),
        Index("ix_delegation_plans_scope_work_item_id", "scope_work_item_id"),
        Index(
            "ix_delegation_plans_required_approver_membership_id",
            "required_approver_membership_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<DelegationPlan {self.short_code} {self.status}>"


class DelegationPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One proposed piece of work.

    Not a task. It has no status, no history, and appears on nobody's list.
    Approval is what turns it into a WorkItem.
    """

    __tablename__ = "delegation_plan_items"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Carried so the composite references below can keep the assignee inside the
    # plan's organization.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    parent_plan_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    type: Mapped[WorkItemType] = mapped_column(
        Enum(WorkItemType, native_enum=False, length=20),
        nullable=False,
        server_default=text(f"'{WorkItemType.TASK.value}'"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Both nullable while drafting. Submission is where they become required:
    # a proposal with a nameless task is not ready to be approved.
    proposed_assignee_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    proposed_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    plan: Mapped[DelegationPlan] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("id", "plan_id", name="uq_delegation_plan_items_id_plan_id"),
        ForeignKeyConstraint(
            ["plan_id", "organization_id"],
            ["delegation_plans.id", "delegation_plans.organization_id"],
            name="fk_delegation_plan_items_plan_same_organization",
            ondelete="CASCADE",
        ),
        # Nesting stays inside one plan.
        ForeignKeyConstraint(
            ["parent_plan_item_id", "plan_id"],
            ["delegation_plan_items.id", "delegation_plan_items.plan_id"],
            name="fk_delegation_plan_items_parent_same_plan",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["proposed_assignee_membership_id", "organization_id"],
            ["memberships.id", "memberships.organization_id"],
            name="fk_delegation_plan_items_assignee_same_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "parent_plan_item_id IS NULL OR parent_plan_item_id <> id",
            name="parent_is_not_self",
        ),
        Index("ix_delegation_plan_items_plan_id", "plan_id"),
    )

    def __repr__(self) -> str:
        return f"<DelegationPlanItem {self.title!r}>"

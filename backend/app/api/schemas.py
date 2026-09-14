"""Request and response shapes.

ORM rows are never returned directly. A model is a storage detail; these are the
contract, and keeping them apart means a column can be renamed without breaking
a caller.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    DelegationPlanStatus,
    MembershipStatus,
    OutboundMessageStatus,
    OutboundMessageType,
    RoleType,
    WorkItemStatus,
    WorkItemType,
)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    role_type: RoleType
    manager_membership_id: uuid.UUID | None
    is_superadmin: bool
    status: MembershipStatus


class RelatedMemberOut(BaseModel):
    membership_id: uuid.UUID
    depth: int


class WorkItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    short_code: str
    type: WorkItemType
    title: str
    description: str | None
    status: WorkItemStatus
    parent_id: uuid.UUID | None
    owner_membership_id: uuid.UUID | None
    due_at: datetime | None
    version: int


class TreeNodeOut(BaseModel):
    depth: int
    item: WorkItemOut


class PlanItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    proposed_assignee_membership_id: uuid.UUID | None
    proposed_due_at: datetime | None
    sort_order: int


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    short_code: str
    status: DelegationPlanStatus
    scope_work_item_id: uuid.UUID
    created_by_membership_id: uuid.UUID
    required_approver_membership_id: uuid.UUID | None
    version: int
    submitted_at: datetime | None
    approved_at: datetime | None
    items: list[PlanItemOut] = Field(default_factory=list)


class OutboundMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_membership_id: uuid.UUID
    message_type: OutboundMessageType
    status: OutboundMessageStatus
    destination: str | None
    body: str
    attempt_count: int
    last_error: str | None


class DecisionOut(BaseModel):
    plan: PlanOut
    created_work_items: list[WorkItemOut]
    notified: int
    already_decided: bool


# --- requests ---


class CreateWorkItemIn(BaseModel):
    type: WorkItemType
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    owner_membership_id: uuid.UUID | None = None
    due_at: datetime | None = None


class CreatePlanIn(BaseModel):
    scope_work_item_id: uuid.UUID


class AddPlanItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    proposed_assignee_membership_id: uuid.UUID | None = None
    proposed_due_at: datetime | None = None


class UpdatePlanItemIn(BaseModel):
    """Every field optional, and *absent* differs from ``null``.

    Callers read which keys were supplied via ``model_fields_set``, so clearing
    an assignee and leaving it untouched stay distinguishable over JSON.
    """

    title: str | None = None
    description: str | None = None
    proposed_assignee_membership_id: uuid.UUID | None = None
    proposed_due_at: datetime | None = None


class DecideIn(BaseModel):
    #: The version the decision was made against. Supply it whenever the plan
    #: was read before deciding; the decision is refused if it has moved.
    expected_version: int | None = None
    comment: str | None = None

"""delegation plans

Revision ID: 46cea40428ef
Revises: 05fc5d11b344
Create Date: 2026-09-13 23:58:39.381234

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '46cea40428ef'
down_revision: str | None = '05fc5d11b344'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('delegation_plans',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('scope_work_item_id', sa.UUID(), nullable=False),
    sa.Column('created_by_membership_id', sa.UUID(), nullable=False),
    sa.Column('required_approver_membership_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', name='delegationplanstatus', native_enum=False, length=20), server_default=sa.text("'DRAFT'"), nullable=False),
    sa.Column('short_code', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'APPROVED') = (approved_at IS NOT NULL)", name=op.f('ck_delegation_plans_approved_at_matches_status')),
    sa.CheckConstraint("status = 'DRAFT' OR required_approver_membership_id IS NOT NULL", name=op.f('ck_delegation_plans_submitted_plans_have_an_approver')),
    sa.CheckConstraint("status = 'DRAFT' OR submitted_at IS NOT NULL", name=op.f('ck_delegation_plans_submitted_plans_record_when')),
    sa.ForeignKeyConstraint(['created_by_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_delegation_plans_creator_same_organization', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_delegation_plans_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['required_approver_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_delegation_plans_approver_same_organization', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['scope_work_item_id', 'organization_id'], ['work_items.id', 'work_items.organization_id'], name='fk_delegation_plans_scope_same_organization', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delegation_plans')),
    sa.UniqueConstraint('id', 'organization_id', name='uq_delegation_plans_id_organization_id'),
    sa.UniqueConstraint('organization_id', 'short_code', name='uq_delegation_plans_organization_id_short_code')
    )
    op.create_index('ix_delegation_plans_organization_id', 'delegation_plans', ['organization_id'], unique=False)
    op.create_index('ix_delegation_plans_required_approver_membership_id', 'delegation_plans', ['required_approver_membership_id'], unique=False)
    op.create_index('ix_delegation_plans_scope_work_item_id', 'delegation_plans', ['scope_work_item_id'], unique=False)
    op.create_index('uq_delegation_plans_one_open_per_scope', 'delegation_plans', ['scope_work_item_id'], unique=True, postgresql_where=sa.text("status IN ('DRAFT', 'PENDING_APPROVAL')"))
    op.create_table('delegation_plan_items',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('parent_plan_item_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.Enum('INITIATIVE', 'RESPONSIBILITY', 'TASK', name='workitemtype', native_enum=False, length=20), server_default=sa.text("'TASK'"), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('proposed_assignee_membership_id', sa.UUID(), nullable=True),
    sa.Column('proposed_due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('parent_plan_item_id IS NULL OR parent_plan_item_id <> id', name=op.f('ck_delegation_plan_items_parent_is_not_self')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_delegation_plan_items_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_plan_item_id', 'plan_id'], ['delegation_plan_items.id', 'delegation_plan_items.plan_id'], name='fk_delegation_plan_items_parent_same_plan', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plan_id', 'organization_id'], ['delegation_plans.id', 'delegation_plans.organization_id'], name='fk_delegation_plan_items_plan_same_organization', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['proposed_assignee_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_delegation_plan_items_assignee_same_organization', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delegation_plan_items')),
    sa.UniqueConstraint('id', 'plan_id', name='uq_delegation_plan_items_id_plan_id')
    )
    op.create_index('ix_delegation_plan_items_plan_id', 'delegation_plan_items', ['plan_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_delegation_plan_items_plan_id', table_name='delegation_plan_items')
    op.drop_table('delegation_plan_items')
    op.drop_index('uq_delegation_plans_one_open_per_scope', table_name='delegation_plans', postgresql_where=sa.text("status IN ('DRAFT', 'PENDING_APPROVAL')"))
    op.drop_index('ix_delegation_plans_scope_work_item_id', table_name='delegation_plans')
    op.drop_index('ix_delegation_plans_required_approver_membership_id', table_name='delegation_plans')
    op.drop_index('ix_delegation_plans_organization_id', table_name='delegation_plans')
    op.drop_table('delegation_plans')

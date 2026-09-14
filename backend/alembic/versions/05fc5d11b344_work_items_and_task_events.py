"""work items and task events

Revision ID: 05fc5d11b344
Revises: e63b63838957
Create Date: 2026-09-13 23:48:38.920086

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '05fc5d11b344'
down_revision: str | None = 'e63b63838957'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('work_items',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.Enum('INITIATIVE', 'RESPONSIBILITY', 'TASK', name='workitemtype', native_enum=False, length=20), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_membership_id', sa.UUID(), nullable=True),
    sa.Column('created_by_membership_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'IN_PROGRESS', 'COMPLETE', 'CANCELLED', name='workitemstatus', native_enum=False, length=20), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('short_code', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type = 'INITIATIVE' OR parent_id IS NOT NULL", name=op.f('ck_work_items_only_initiatives_are_roots')),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name=op.f('ck_work_items_parent_is_not_self')),
    sa.ForeignKeyConstraint(['created_by_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_work_items_creator_same_organization', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_work_items_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_work_items_owner_same_organization', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['parent_id', 'organization_id'], ['work_items.id', 'work_items.organization_id'], name='fk_work_items_parent_same_organization', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_items')),
    sa.UniqueConstraint('id', 'organization_id', name='uq_work_items_id_organization_id'),
    sa.UniqueConstraint('organization_id', 'short_code', name='uq_work_items_organization_id_short_code')
    )
    op.create_index('ix_work_items_organization_id', 'work_items', ['organization_id'], unique=False)
    op.create_index('ix_work_items_owner_membership_id', 'work_items', ['owner_membership_id'], unique=False)
    op.create_index('ix_work_items_parent_id', 'work_items', ['parent_id'], unique=False)
    op.create_table('task_events',
    sa.Column('work_item_id', sa.UUID(), nullable=False),
    sa.Column('actor_membership_id', sa.UUID(), nullable=True),
    sa.Column('event_type', sa.Enum('WORK_CREATED', 'ASSIGNED', 'STARTED', 'COMPLETED', 'CANCELLED', name='taskeventtype', native_enum=False, length=30), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_membership_id'], ['memberships.id'], name=op.f('fk_task_events_actor_membership_id_memberships'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], name=op.f('fk_task_events_work_item_id_work_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_events'))
    )
    op.create_index('ix_task_events_created_at', 'task_events', ['created_at'], unique=False)
    op.create_index('ix_task_events_work_item_id', 'task_events', ['work_item_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_task_events_work_item_id', table_name='task_events')
    op.drop_index('ix_task_events_created_at', table_name='task_events')
    op.drop_table('task_events')
    op.drop_index('ix_work_items_parent_id', table_name='work_items')
    op.drop_index('ix_work_items_owner_membership_id', table_name='work_items')
    op.drop_index('ix_work_items_organization_id', table_name='work_items')
    op.drop_table('work_items')

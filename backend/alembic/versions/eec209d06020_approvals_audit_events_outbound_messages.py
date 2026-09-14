"""approvals, audit events, outbound messages

Revision ID: eec209d06020
Revises: 46cea40428ef
Create Date: 2026-09-14 00:12:45.503073

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'eec209d06020'
down_revision: str | None = '46cea40428ef'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audit_events',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('actor_membership_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.Enum('APPROVE_PLAN', 'REJECT_PLAN', name='auditaction', native_enum=False, length=40), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('after_state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_audit_events_actor_same_organization', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_audit_events_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index('ix_audit_events_created_at', 'audit_events', ['created_at'], unique=False)
    op.create_index('ix_audit_events_organization_id', 'audit_events', ['organization_id'], unique=False)
    op.create_index('ix_audit_events_target_id', 'audit_events', ['target_id'], unique=False)
    op.create_table('outbound_messages',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('recipient_membership_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Enum('IMESSAGE', 'SMS', name='messagingchannel', native_enum=False, length=20), nullable=False),
    sa.Column('destination', sa.String(length=320), nullable=True),
    sa.Column('message_type', sa.Enum('ASSIGNMENT', 'PLAN_SUBMITTED', 'PLAN_APPROVED', 'PLAN_REJECTED', name='outboundmessagetype', native_enum=False, length=30), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'SENT', 'FAILED', name='outboundmessagestatus', native_enum=False, length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("destination IS NOT NULL OR status = 'FAILED'", name=op.f('ck_outbound_messages_undeliverable_rows_are_marked_failed')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_outbound_messages_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_outbound_messages_recipient_same_organization', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbound_messages'))
    )
    op.create_index('ix_outbound_messages_organization_id', 'outbound_messages', ['organization_id'], unique=False)
    op.create_index('ix_outbound_messages_status_available_at', 'outbound_messages', ['status', 'available_at'], unique=False)
    op.create_table('approvals',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('plan_version', sa.Integer(), nullable=False),
    sa.Column('approver_membership_id', sa.UUID(), nullable=False),
    sa.Column('decision', sa.Enum('APPROVED', 'REJECTED', name='approvaldecision', native_enum=False, length=20), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['approver_membership_id'], ['memberships.id'], name=op.f('fk_approvals_approver_membership_id_memberships'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plan_id'], ['delegation_plans.id'], name=op.f('fk_approvals_plan_id_delegation_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals'))
    )
    op.create_index('ix_approvals_plan_id', 'approvals', ['plan_id'], unique=False)
    op.create_index('uq_approvals_one_approval_per_plan', 'approvals', ['plan_id'], unique=True, postgresql_where=sa.text("decision = 'APPROVED'"))


def downgrade() -> None:
    op.drop_index('uq_approvals_one_approval_per_plan', table_name='approvals', postgresql_where=sa.text("decision = 'APPROVED'"))
    op.drop_index('ix_approvals_plan_id', table_name='approvals')
    op.drop_table('approvals')
    op.drop_index('ix_outbound_messages_status_available_at', table_name='outbound_messages')
    op.drop_index('ix_outbound_messages_organization_id', table_name='outbound_messages')
    op.drop_table('outbound_messages')
    op.drop_index('ix_audit_events_target_id', table_name='audit_events')
    op.drop_index('ix_audit_events_organization_id', table_name='audit_events')
    op.drop_index('ix_audit_events_created_at', table_name='audit_events')
    op.drop_table('audit_events')

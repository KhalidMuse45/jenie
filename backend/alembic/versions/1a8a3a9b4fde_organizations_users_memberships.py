"""organizations, users, memberships

Revision ID: 1a8a3a9b4fde
Revises:
Create Date: 2026-09-13 20:21:31.836370

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '1a8a3a9b4fde'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('organizations',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default=sa.text("'America/Chicago'"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations'))
    )
    op.create_table('users',
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_table('memberships',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('role_type', sa.Enum('MEMBER', 'LEAD', 'VP', 'PRESIDENT', name='roletype', native_enum=False, length=20), nullable=False),
    sa.Column('manager_membership_id', sa.UUID(), nullable=True),
    sa.Column('is_superadmin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', name='membershipstatus', native_enum=False, length=20), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('manager_membership_id IS NULL OR manager_membership_id <> id', name=op.f('ck_memberships_manager_is_not_self')),
    sa.ForeignKeyConstraint(['manager_membership_id', 'organization_id'], ['memberships.id', 'memberships.organization_id'], name='fk_memberships_manager_same_organization', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_memberships_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships')),
    sa.UniqueConstraint('id', 'organization_id', name='uq_memberships_id_organization_id'),
    sa.UniqueConstraint('organization_id', 'user_id', name='uq_memberships_organization_id_user_id')
    )
    op.create_index('ix_memberships_manager_membership_id', 'memberships', ['manager_membership_id'], unique=False)
    op.create_index('ix_memberships_organization_id', 'memberships', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_memberships_organization_id', table_name='memberships')
    op.drop_index('ix_memberships_manager_membership_id', table_name='memberships')
    op.drop_table('memberships')
    op.drop_table('users')
    op.drop_table('organizations')

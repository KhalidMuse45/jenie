"""messaging identities

Revision ID: e63b63838957
Revises: 1a8a3a9b4fde
Create Date: 2026-09-13 23:31:44.117491

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e63b63838957'
down_revision: str | None = '1a8a3a9b4fde'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('messaging_identities',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Enum('IMESSAGE', 'SMS', name='messagingchannel', native_enum=False, length=20), nullable=False),
    sa.Column('address_raw', sa.String(length=320), nullable=False),
    sa.Column('address_norm', sa.String(length=320), nullable=False),
    sa.Column('verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('verified = false OR verified_at IS NOT NULL', name=op.f('ck_messaging_identities_verified_records_when')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_messaging_identities_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messaging_identities')),
    sa.UniqueConstraint('channel', 'address_norm', name='uq_messaging_identities_channel_address_norm')
    )


def downgrade() -> None:
    op.drop_table('messaging_identities')

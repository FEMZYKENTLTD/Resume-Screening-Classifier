"""add is_admin flag to users (admin dashboard access control)

Revision ID: 20260826_add_user_admin
Revises: 20260825_add_user_id_to_results
Create Date: 2026-08-26 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260826_add_user_admin'
down_revision = '20260825_add_user_id_to_results'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('is_admin', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade():
    op.drop_column('users', 'is_admin')

"""add users.token_version (server-side session revocation on logout)

Revision ID: 20260902_token_version
Revises: 20260826_add_user_admin
Create Date: 2026-09-02 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260902_token_version'
down_revision = '20260826_add_user_admin'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False,
                  server_default='0'),
    )


def downgrade():
    op.drop_column('users', 'token_version')

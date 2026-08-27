"""link analysis jobs to user accounts (account history)

Revision ID: 20260825_add_user_id_to_results
Revises: 20260825_enhanced_fields
Create Date: 2026-08-25 20:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260825_add_user_id_to_results'
down_revision = '20260825_enhanced_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('resume_results', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('ix_resume_results_user_id', 'resume_results', ['user_id'])


def downgrade():
    op.drop_index('ix_resume_results_user_id', table_name='resume_results')
    op.drop_column('resume_results', 'user_id')

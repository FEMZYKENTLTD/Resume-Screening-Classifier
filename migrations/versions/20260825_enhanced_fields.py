"""enhanced analysis fields: dedup hash, role, extracted fields, match details

Revision ID: 20260825_enhanced_fields
Revises: 20260825_seed_demo_data
Create Date: 2026-08-25 14:00:00.000000

Supports: duplicate prevention (unique resume_hash), role classification,
resume field extraction, and semantic match breakdown.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260825_enhanced_fields'
down_revision = '20260825_seed_demo_data'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('resume_results', sa.Column('resume_hash', sa.String(), nullable=True))
    op.add_column('resume_results', sa.Column('predicted_role', sa.String(), nullable=True))
    op.add_column('resume_results', sa.Column('extracted_fields', sa.Text(), nullable=True))
    op.add_column('resume_results', sa.Column('match_details', sa.Text(), nullable=True))
    op.create_index('ix_resume_results_hash', 'resume_results', ['resume_hash'], unique=True)


def downgrade():
    op.drop_index('ix_resume_results_hash', table_name='resume_results')
    op.drop_column('resume_results', 'match_details')
    op.drop_column('resume_results', 'extracted_fields')
    op.drop_column('resume_results', 'predicted_role')
    op.drop_column('resume_results', 'resume_hash')

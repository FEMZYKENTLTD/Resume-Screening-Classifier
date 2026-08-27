"""add skills_extracted column

Revision ID: 20260821_add_skills_extracted
Revises: 20260821_create_resume_results
Create Date: 2026-08-21 22:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '20260821_add_skills_extracted'
down_revision = '20260821_create_resume_results'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('resume_results', sa.Column('skills_extracted', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('resume_results', 'skills_extracted')

"""create resume_results table

Revision ID: 20260821_create_resume_results
Revises: 
Create Date: 2026-08-21 21:05:00.000000

"""
from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = '20260821_create_resume_results'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Create enum type for job status
    jobstatus = sa.Enum('queued', 'processing', 'completed', 'failed', name='jobstatus')

    op.create_table(
        'resume_results',
        sa.Column('job_id', sa.String(), primary_key=True, index=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('resume_text', sa.Text(), nullable=True),
        sa.Column('job_description', sa.Text(), nullable=True),
        sa.Column('jd_match_score', sa.Float(), nullable=True),
        sa.Column('status', jobstatus, nullable=False, server_default='queued'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('resume_results')
    op.execute("DROP TYPE jobstatus")

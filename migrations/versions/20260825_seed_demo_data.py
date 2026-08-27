"""seed demo data (replaces docker-entrypoint init.sql)

Revision ID: 20260825_seed_demo_data
Revises: 890630346961
Create Date: 2026-08-25 12:00:00.000000

The old init.sql was mounted into docker-entrypoint-initdb.d, which runs
BEFORE migrations — so its INSERTs failed on a fresh database and killed
the db container's first boot. The seed data now lives here, where it can
only run after the tables exist.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260825_seed_demo_data'
down_revision = '890630346961'
branch_labels = None
depends_on = None

users = sa.table(
    'users',
    sa.column('username', sa.String),
    sa.column('password_hash', sa.Text),
    sa.column('email', sa.String),
)

resumes = sa.table(
    'resumes',
    sa.column('user_id', sa.Integer),
    sa.column('filename', sa.String),
    sa.column('content', sa.Text),
)

analysis_results = sa.table(
    'analysis_results',
    sa.column('resume_id', sa.Integer),
    sa.column('job_description', sa.Text),
    sa.column('score', sa.Integer),
    sa.column('matched_keywords', sa.Text),
)


def upgrade():
    op.bulk_insert(users, [
        {'username': 'hr', 'password_hash': 'hashedpassword',
         'email': 'hr@example.com'},
    ])
    op.bulk_insert(resumes, [
        {'user_id': 1, 'filename': 'resume1.pdf',
         'content': 'Python, SQL, Machine Learning'},
    ])
    op.bulk_insert(analysis_results, [
        {'resume_id': 1, 'job_description': 'Data Scientist role',
         'score': 85, 'matched_keywords': 'python,sql,machine,learning'},
    ])


def downgrade():
    op.execute("DELETE FROM analysis_results WHERE resume_id = 1")
    op.execute("DELETE FROM resumes WHERE user_id = 1")
    op.execute("DELETE FROM users WHERE username = 'hr'")

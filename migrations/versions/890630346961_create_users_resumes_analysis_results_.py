from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
# Legacy demo tables from the original capstone UI. Chained AFTER the
# resume_results branch so the migration history has a single head.
revision = '890630346961'
down_revision = '20260821_add_skills_extracted'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('password_hash', sa.Text, nullable=False),
        sa.Column('email', sa.String(100), unique=True, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.now())
    )

    op.create_table(
        'resumes',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
        sa.Column('filename', sa.String(255)),
        sa.Column('content', sa.Text),
        sa.Column('uploaded_at', sa.TIMESTAMP, server_default=sa.func.now())
    )

    op.create_table(
        'analysis_results',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('resume_id', sa.Integer, sa.ForeignKey('resumes.id')),
        sa.Column('job_description', sa.Text),
        sa.Column('score', sa.Integer),
        sa.Column('matched_keywords', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.now())
    )

    # Optional: add indexes for performance
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_resumes_user_id', 'resumes', ['user_id'])
    op.create_index('ix_analysis_results_resume_id', 'analysis_results', ['resume_id'])

def downgrade():
    op.drop_index('ix_analysis_results_resume_id', table_name='analysis_results')
    op.drop_index('ix_resumes_user_id', table_name='resumes')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('analysis_results')
    op.drop_table('resumes')
    op.drop_table('users')

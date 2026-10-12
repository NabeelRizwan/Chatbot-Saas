"""Add opt-in customer experience records without altering account or knowledge data."""
from alembic import op
import sqlalchemy as sa

revision = "20261012_01"
down_revision = "20260928_01"
branch_labels = None
depends_on = None

TABLE_COLUMNS = {'experience_settings': ['approved_faq_enabled', 'bot_id', 'corner_style', 'density', 'enabled', 'font_family', 'hosted_chat_enabled', 'lead_consent_text', 'lead_form_enabled', 'organization_id', 'product_cards_enabled', 'suggested_questions', 'theme', 'updated_at'], 'experience_faqs': ['aliases', 'answer', 'approved', 'approved_by_user_id', 'bot_id', 'created_at', 'enabled', 'id', 'organization_id', 'question', 'source_document_id', 'source_fingerprint', 'source_url', 'updated_at'], 'experience_faq_aliases': ['bot_id', 'faq_id', 'id', 'normalized_question', 'question_hash'], 'experience_products': ['bot_id', 'created_at', 'currency', 'description', 'enabled', 'id', 'image_url', 'organization_id', 'price_amount', 'source_document_id', 'source_fingerprint', 'title', 'updated_at', 'url'], 'experience_leads': ['bot_id', 'consent_at', 'created_at', 'email', 'email_normalized', 'id', 'message', 'name', 'organization_id', 'phone', 'status'], 'experience_lead_submissions': ['bot_id', 'consent_at', 'consent_text', 'id', 'idempotency_key', 'lead_id', 'message', 'name', 'payload_hash', 'phone', 'session_id'], 'experience_test_cases': ['bot_id', 'created_at', 'enabled', 'expected_answer', 'forbidden_phrases', 'id', 'organization_id', 'question', 'required_phrases', 'updated_at'], 'experience_test_runs': ['bot_id', 'completed_at', 'created_at', 'created_by_user_id', 'id', 'lease_expires_at', 'lease_token', 'model', 'organization_id', 'provider', 'status'], 'experience_test_results': ['answer', 'case_id', 'error', 'expected_answer', 'forbidden_matches', 'forbidden_phrases', 'id', 'latency_ms', 'missing_phrases', 'position', 'question', 'required_phrases', 'run_id', 'sources', 'status'], 'experience_integrations': ['bot_id', 'config_json', 'organization_id', 'updated_at']}

def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(TABLE_COLUMNS)
    if present:
        if present != set(TABLE_COLUMNS):
            raise RuntimeError("Partial customer experience schema requires reconciliation")
        inspector = sa.inspect(op.get_bind())
        for name, expected in TABLE_COLUMNS.items():
            if sorted(column["name"] for column in inspector.get_columns(name)) != expected:
                raise RuntimeError(f"Existing {name} does not match the experience migration")
        return
    op.create_table('experience_settings',
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('suggested_questions', sa.JSON(), nullable=False),
    sa.Column('hosted_chat_enabled', sa.Boolean(), nullable=False),
    sa.Column('lead_form_enabled', sa.Boolean(), nullable=False),
    sa.Column('approved_faq_enabled', sa.Boolean(), nullable=False),
    sa.Column('product_cards_enabled', sa.Boolean(), nullable=False),
    sa.Column('font_family', sa.String(length=16), nullable=False),
    sa.Column('density', sa.String(length=16), nullable=False),
    sa.Column('theme', sa.String(length=16), nullable=False),
    sa.Column('corner_style', sa.String(length=16), nullable=False),
    sa.Column('lead_consent_text', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_settings_bot_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('bot_id')
    )
    op.create_index(op.f('ix_experience_settings_organization_id'), 'experience_settings', ['organization_id'], unique=False)
    op.create_table('experience_faqs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('aliases', sa.JSON(), nullable=False),
    sa.Column('source_document_id', sa.Integer(), nullable=True),
    sa.Column('source_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('approved', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_faqs_bot_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experience_faqs_bot_id'), 'experience_faqs', ['bot_id'], unique=False)
    op.create_index(op.f('ix_experience_faqs_organization_id'), 'experience_faqs', ['organization_id'], unique=False)
    op.create_table('experience_faq_aliases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('faq_id', sa.Integer(), nullable=False),
    sa.Column('normalized_question', sa.String(length=1000), nullable=False),
    sa.Column('question_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['faq_id'], ['experience_faqs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id', 'question_hash', name='uq_experience_faq_alias')
    )
    op.create_index(op.f('ix_experience_faq_aliases_faq_id'), 'experience_faq_aliases', ['faq_id'], unique=False)
    op.create_table('experience_products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('image_url', sa.Text(), nullable=True),
    sa.Column('price_amount', sa.String(length=32), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('source_document_id', sa.Integer(), nullable=True),
    sa.Column('source_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_products_bot_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experience_products_bot_id'), 'experience_products', ['bot_id'], unique=False)
    op.create_index(op.f('ix_experience_products_organization_id'), 'experience_products', ['organization_id'], unique=False)
    op.create_table('experience_leads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('email_normalized', sa.String(length=254), nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('consent_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_leads_bot_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id', 'email_normalized', name='uq_experience_lead_email')
    )
    op.create_index(op.f('ix_experience_leads_bot_id'), 'experience_leads', ['bot_id'], unique=False)
    op.create_index(op.f('ix_experience_leads_organization_id'), 'experience_leads', ['organization_id'], unique=False)
    op.create_table('experience_lead_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lead_id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('consent_text', sa.Text(), nullable=False),
    sa.Column('consent_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lead_id'], ['experience_leads.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id', 'session_id', 'idempotency_key', name='uq_experience_lead_submission')
    )
    op.create_index(op.f('ix_experience_lead_submissions_lead_id'), 'experience_lead_submissions', ['lead_id'], unique=False)
    op.create_table('experience_test_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('expected_answer', sa.Text(), nullable=False),
    sa.Column('required_phrases', sa.JSON(), nullable=False),
    sa.Column('forbidden_phrases', sa.JSON(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_test_cases_bot_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experience_test_cases_bot_id'), 'experience_test_cases', ['bot_id'], unique=False)
    op.create_index(op.f('ix_experience_test_cases_organization_id'), 'experience_test_cases', ['organization_id'], unique=False)
    op.create_table('experience_test_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('lease_token', sa.String(length=64), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
    sa.Column('provider', sa.String(length=100), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_test_runs_bot_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experience_test_runs_bot_id'), 'experience_test_runs', ['bot_id'], unique=False)
    op.create_index(op.f('ix_experience_test_runs_organization_id'), 'experience_test_runs', ['organization_id'], unique=False)
    op.create_table('experience_test_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('expected_answer', sa.Text(), nullable=False),
    sa.Column('required_phrases', sa.JSON(), nullable=False),
    sa.Column('forbidden_phrases', sa.JSON(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('missing_phrases', sa.JSON(), nullable=False),
    sa.Column('forbidden_matches', sa.JSON(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['experience_test_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'position', name='uq_experience_test_position')
    )
    op.create_index(op.f('ix_experience_test_results_run_id'), 'experience_test_results', ['run_id'], unique=False)
    op.create_table('experience_integrations',
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('config_json', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id', 'organization_id'], ['bots.id', 'bots.organization_id'], name='fk_experience_integrations_bot_owner', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('bot_id')
    )
    op.create_index(op.f('ix_experience_integrations_organization_id'), 'experience_integrations', ['organization_id'], unique=False)

def downgrade():
    op.drop_table("experience_integrations")
    op.drop_table("experience_test_results")
    op.drop_table("experience_test_runs")
    op.drop_table("experience_test_cases")
    op.drop_table("experience_lead_submissions")
    op.drop_table("experience_leads")
    op.drop_table("experience_products")
    op.drop_table("experience_faq_aliases")
    op.drop_table("experience_faqs")
    op.drop_table("experience_settings")

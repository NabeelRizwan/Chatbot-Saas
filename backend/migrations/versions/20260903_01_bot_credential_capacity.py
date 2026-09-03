"""Add per-profile bot capacity; retain encrypted keys and valid assignments.

Revision ID: 20260903_01
Revises: 20260902_02
"""
from alembic import op
from sqlalchemy import text

revision = "20260903_01"
down_revision = "20260902_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drain old application writers before this one-off release step. Use the
    # same lock as new lifecycle writers; never decrypt/re-encrypt any secret.
    op.execute("SELECT pg_advisory_xact_lock(73421, 1)")
    op.execute("ALTER TABLE platform_api_keys ADD COLUMN IF NOT EXISTS max_bot_assignments INTEGER NOT NULL DEFAULT 2")
    # Fail transactionally for invalid canonical references instead of silently
    # deleting assignments or changing a customer's BYOK/provider settings.
    invalid = op.get_bind().execute(text(
        "SELECT count(*) FROM bots b JOIN platform_api_keys k ON k.id=b.platform_credential_id "
        "WHERE b.provider <> k.provider OR NULLIF(btrim(b.provider_api_key), '') IS NOT NULL"
    )).scalar_one()
    if invalid:
        raise RuntimeError("Credential migration stopped: incompatible existing bot assignments require administrator review. No assignments were removed.")
    op.execute(
        "UPDATE bots b SET platform_credential_id=k.id FROM platform_api_keys k "
        "WHERE k.allocated_to_bot_id=b.id AND b.platform_credential_id IS NULL "
        "AND b.provider=k.provider AND NULLIF(btrim(b.provider_api_key), '') IS NULL"
    )
    # Preserve existing capacities and all valid bot references, even if an
    # earlier deployment already populated several bot-side references.
    op.execute(
        "UPDATE platform_api_keys k SET max_bot_assignments=GREATEST(COALESCE(k.max_bot_assignments, 2), "
        "(SELECT count(*) FROM bots b WHERE b.platform_credential_id=k.id)), "
        "status=CASE WHEN k.status='disabled' THEN 'disabled' "
        "WHEN EXISTS (SELECT 1 FROM bots b WHERE b.platform_credential_id=k.id) THEN 'assigned' ELSE 'available' END"
    )
    op.execute("ALTER TABLE platform_api_keys ALTER COLUMN max_bot_assignments SET DEFAULT 2")
    op.execute("ALTER TABLE platform_api_keys ALTER COLUMN max_bot_assignments SET NOT NULL")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname='ck_platform_key_bot_capacity'
                  AND conrelid='platform_api_keys'::regclass
            ) THEN
                ALTER TABLE platform_api_keys ADD CONSTRAINT ck_platform_key_bot_capacity
                CHECK (max_bot_assignments >= 1);
            END IF;
        END $$
    """)


def downgrade() -> None:
    raise NotImplementedError("Capacity rollout is additive; downgrading to one-to-one writers is unsafe while profiles are shared.")

"""Enable row level security on every public table.

On Supabase the public schema is exposed through its Data API. With RLS enabled and no policies,
the anon/authenticated keys can read nothing; this backend connects as the database owner, which
bypasses RLS, so the app is unaffected. On a plain Postgres it is harmless.

Revision ID: b7d2e4f1a9c3
Revises: a3f9c1d27b58
"""

from alembic import op

revision = "b7d2e4f1a9c3"
down_revision = "a3f9c1d27b58"
branch_labels = None
depends_on = None

ENABLE = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
  END LOOP;
END $$;
"""

DISABLE = ENABLE.replace("ENABLE ROW", "DISABLE ROW")


def upgrade() -> None:
    op.execute(ENABLE)


def downgrade() -> None:
    op.execute(DISABLE)

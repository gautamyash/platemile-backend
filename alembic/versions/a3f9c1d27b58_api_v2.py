"""API v2: logs, steps, settings, targets override, plans, saved meals, reports, foods catalogue.

Revision ID: a3f9c1d27b58
Revises: 741987d22c35
Create Date: 2026-10-02 12:00:00

The initial migration (741987d22c35) created users, user_profiles, credit_ledger and ai_requests only.
This revision adds everything else that app/models.py defines, plus users.name and users.health_consent_at.
"""

import sqlalchemy as sa
from alembic import op

revision = "a3f9c1d27b58"
down_revision = "1fffaa7c590a"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


_created: set[str] = set()


def _create_table(name: str, *cols) -> None:
    """Create the table unless an earlier migration already did (idempotent chain)."""
    if sa.inspect(op.get_bind()).has_table(name):
        return
    op.create_table(name, *cols)
    _created.add(name)


def _create_index(name: str, table: str, cols: list[str]) -> None:
    if table in _created:
        op.create_index(name, table, cols)


def _user_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE")


def _add_user_column_if_missing(name: str, column: sa.Column) -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if name not in existing:
        op.add_column("users", column)


def upgrade() -> None:
    # --- users: new columns ---
    _add_user_column_if_missing("deleted_at", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    _add_user_column_if_missing("health_consent_at", sa.Column("health_consent_at", sa.DateTime(timezone=True), nullable=True))
    _add_user_column_if_missing("name", sa.Column("name", sa.String(length=120), nullable=True))

    # --- tables used by the earlier API but missing from the initial migration ---
    _create_table(
        "food_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("logged_on", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(12), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("quantity", sa.String(60), nullable=False),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("fibre_g", sa.Float(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _user_fk(),
    )
    _create_index("ix_food_logs_user_id", "food_logs", ["user_id"])
    _create_index("ix_food_logs_logged_on", "food_logs", ["logged_on"])

    _create_table(
        "water_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("logged_on", sa.Date(), nullable=False),
        sa.Column("ml", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _user_fk(),
    )
    _create_index("ix_water_logs_user_id", "water_logs", ["user_id"])
    _create_index("ix_water_logs_logged_on", "water_logs", ["logged_on"])

    _create_table(
        "weight_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("logged_on", sa.Date(), nullable=False),
        sa.Column("kg", sa.Float(), nullable=False),
        _user_fk(),
        sa.UniqueConstraint("user_id", "logged_on"),
    )
    _create_index("ix_weight_logs_user_id", "weight_logs", ["user_id"])

    _create_table(
        "steps_daily",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("steps", sa.Integer(), nullable=False),
        _user_fk(),
    )

    _create_table(
        "deleted_identities",
        sa.Column("sub_hash", sa.String(64), primary_key=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )

    # --- new in API v2 ---
    _create_table(
        "user_settings",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        _user_fk(),
    )

    _create_table(
        "target_overrides",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("kcal", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Integer(), nullable=False),
        sa.Column("carbs_g", sa.Integer(), nullable=False),
        sa.Column("fat_g", sa.Integer(), nullable=False),
        sa.Column("water_ml", sa.Integer(), nullable=True),
        sa.Column("steps_goal", sa.Integer(), nullable=True),
        _user_fk(),
    )

    _create_table(
        "meal_plan_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(12), nullable=False),
        sa.Column("meal", sa.JSON(), nullable=False),
        sa.Column("logged", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _user_fk(),
        sa.UniqueConstraint("user_id", "plan_date", "meal_type"),
    )
    _create_index("ix_meal_plan_entries_user_id", "meal_plan_entries", ["user_id"])
    _create_index("ix_meal_plan_entries_plan_date", "meal_plan_entries", ["plan_date"])

    _create_table(
        "saved_meals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("meal", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _user_fk(),
        sa.UniqueConstraint("user_id", "name"),
    )
    _create_index("ix_saved_meals_user_id", "saved_meals", ["user_id"])

    _create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _user_fk(),
    )
    _create_index("ix_reports_user_id", "reports", ["user_id"])

    _create_table(
        "foods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("aliases", sa.Text(), nullable=False),
        sa.Column("serving", sa.String(60), nullable=False),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("fibre_g", sa.Float(), nullable=False),
        sa.Column("popularity", sa.Integer(), nullable=False),
    )
    _create_index("ix_foods_popularity", "foods", ["popularity"])
    # The foods rows themselves are inserted by app.seed_foods.seed_foods() at app startup (idempotent).


def downgrade() -> None:
    for table, index in [
        ("foods", "ix_foods_popularity"),
        ("reports", "ix_reports_user_id"),
        ("saved_meals", "ix_saved_meals_user_id"),
    ]:
        op.drop_index(index, table_name=table)
        op.drop_table(table)
    op.drop_index("ix_meal_plan_entries_plan_date", table_name="meal_plan_entries")
    op.drop_index("ix_meal_plan_entries_user_id", table_name="meal_plan_entries")
    op.drop_table("meal_plan_entries")
    op.drop_table("target_overrides")
    op.drop_table("user_settings")
    op.drop_column("users", "name")

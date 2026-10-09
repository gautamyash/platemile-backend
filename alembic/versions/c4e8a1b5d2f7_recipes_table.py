"""Recipes table (meal engine data lives in the database).

Revision ID: c4e8a1b5d2f7
Revises: b7d2e4f1a9c3
"""

import sqlalchemy as sa
from alembic import op

revision = "c4e8a1b5d2f7"
down_revision = "b7d2e4f1a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(60), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_recipes_active", "recipes", ["active"])
    op.execute("ALTER TABLE public.recipes ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_recipes_active", table_name="recipes")
    op.drop_table("recipes")

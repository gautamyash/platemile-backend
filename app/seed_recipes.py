"""Recipes in the database.

`seed_recipes` copies the recipes from app/meal_data into the `recipes` table (insert-if-missing by name, so edits made
in the database are never overwritten), then loads every active row into the meal engine. If the database cannot be
read the engine keeps serving the recipes from the data files.
"""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import meal_engine
from app.models import RecipeRow

log = logging.getLogger("seed")


async def seed_recipes(maker: async_sessionmaker[AsyncSession]) -> int:
    """Seeds missing recipes, reloads the engine from the database. Returns the number of recipes served."""
    rows = [
        {"name": d["name"].strip()[:120], "data": d, "source": src, "active": True}
        for src, d in meal_engine.file_recipe_dicts()
        if isinstance(d, dict) and isinstance(d.get("name"), str)
    ]
    async with maker() as session:
        if rows:
            stmt = pg_insert(RecipeRow).values(rows).on_conflict_do_nothing(index_elements=["name"])
            added = len((await session.execute(stmt.returning(RecipeRow.id))).all())
            await session.commit()
            if added:
                log.info("seeded %d recipes", added)
        found = (await session.execute(
            select(RecipeRow.source, RecipeRow.data).where(RecipeRow.active.is_(True)).order_by(RecipeRow.id)
        )).all()
    n = meal_engine.install_recipes([(src or "db", data) for src, data in found])
    log.info("meal engine serving %d recipes from the database", n)
    return n

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:dev@localhost:5433/dietapp_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380")
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"

import asyncio

import asyncpg
import pytest_asyncio
from sqlalchemy.engine import make_url
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.db import Base, get_session
from app.main import app
from app.seed_foods import seed_foods


def _ensure_test_database() -> None:
    """Create the *_test database if missing, and refuse to run against any other one.

    The fixture below drops every table, so it must never point at the real database.
    """
    url = make_url(os.environ["DATABASE_URL"])
    assert url.database and url.database.endswith("_test"), (
        f"Refusing to run tests against {url.database!r}: the database name must end with _test"
    )

    async def go() -> None:
        conn = await asyncpg.connect(
            host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
        )
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", url.database)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await conn.close()

    asyncio.run(go())


_ensure_test_database()


@pytest_asyncio.fixture
async def client(monkeypatch):
    from app.config import settings

    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    await seed_foods(maker)

    async def override():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override

    claims = {"sub": "sub-1", "email": "a@example.com"}

    async def fake_verify(token: str) -> dict:
        from app.google_auth import InvalidGoogleToken

        if token.startswith("bad"):
            raise InvalidGoogleToken("bad")
        return {**claims, "sub": token.split(":")[1] if ":" in token else "sub-1"}

    monkeypatch.setattr("app.routers.auth.verify_google_id_token", fake_verify)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def login(client, sub="sub-1"):
    r = await client.post("/auth/google", json={"id_token": f"tok:{sub}:xxxxxxxxxxxxxxxxxxxxxxxx"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()


PROFILE = {
    "goal": "lose_weight", "diet_type": "veg", "sex": "female", "birth_year": 1995, "height_cm": 160,
    "weight_kg": 70, "activity_level": "light", "meals_per_day": 3,
    "restrictions": {"allergies": ["peanut"], "dislikes": [], "cuisines": []}, "health_consent": True,
}

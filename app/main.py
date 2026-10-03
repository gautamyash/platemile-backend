import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.db import SessionLocal
from app.routers import (
    account,
    ai,
    auth,
    credits,
    foods,
    logs,
    plans,
    profile,
    progress,
    reports,
    saved,
    settings,
)
from app.seed_foods import seed_foods


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await seed_foods(SessionLocal)
    except Exception:  # e.g. migrations not applied yet; the API must still start
        logging.getLogger("seed").exception("food catalogue seeding failed")
    yield


app = FastAPI(title="PlateMile API", version="0.3.0", lifespan=lifespan)
for r in (auth, profile, logs, foods, progress, plans, saved, settings, credits, ai, reports, account):
    app.include_router(r.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.models import (
    AiRequest,
    CreditLedger,
    DeletedIdentity,
    FoodLog,
    MealPlanEntry,
    Report,
    SavedMeal,
    StepsDaily,
    TargetOverride,
    User,
    UserProfile,
    UserSettings,
    WaterLog,
    WeightLog,
)

router = APIRouter(tags=["account"])


def sub_hash(sub: str) -> str:
    return hashlib.sha256(f"{settings.jwt_secret}:{sub}".encode()).hexdigest()


@router.delete("/me", status_code=204)
async def delete_account(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Permanently deletes the account and all its data (cascades to every table)."""
    session.add(DeletedIdentity(sub_hash=sub_hash(user.google_sub)))
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()


@router.get("/me/export")
async def export_data(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    async def rows(model, order):
        return list((await session.execute(select(model).where(model.user_id == user.id).order_by(order))).scalars())

    def plain(obj):
        return {c.name: (v.isoformat() if hasattr(v := getattr(obj, c.name), "isoformat") else v) for c in obj.__table__.columns}

    profile = await session.get(UserProfile, user.id)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {"email": user.email, "name": user.name, "created_at": user.created_at.isoformat()},
        "profile": plain(profile) if profile else None,
        "food_logs": [plain(r) for r in await rows(FoodLog, FoodLog.logged_on)],
        "water_logs": [plain(r) for r in await rows(WaterLog, WaterLog.logged_on)],
        "weight_logs": [plain(r) for r in await rows(WeightLog, WeightLog.logged_on)],
        "steps": [plain(r) for r in await rows(StepsDaily, StepsDaily.day)],
        "settings": plain(settings_row) if (settings_row := await session.get(UserSettings, user.id)) else None,
        "target_override": plain(ov) if (ov := await session.get(TargetOverride, user.id)) else None,
        "meal_plan_entries": [plain(r) for r in await rows(MealPlanEntry, MealPlanEntry.plan_date)],
        "saved_meals": [plain(r) for r in await rows(SavedMeal, SavedMeal.created_at)],
        "reports": [plain(r) for r in await rows(Report, Report.created_at)],
        "credit_ledger": [plain(r) for r in await rows(CreditLedger, CreditLedger.id)],
        "ai_requests": [plain(r) for r in await rows(AiRequest, AiRequest.created_at)],
    }


DELETION_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Delete your PlateMile account</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;line-height:1.6;color:#2A241A;background:#FBF6EC}h1{font-size:26px}</style></head>
<body><h1>Delete your PlateMile account</h1>
<p>You can delete your account and data at any time.</p>
<h2>In the app</h2>
<p>Open <b>Me &rarr; Privacy &rarr; Delete account</b> and confirm.</p>
<h2>Without the app</h2>
<p>Email <b>{email}</b> from the Google account you signed in with, with the subject "Delete my account". We will delete your account within 30 days and confirm by email.</p>
<h2>What is deleted</h2>
<p>Your profile, meals, water, weight and step records, credit history and AI request history are permanently deleted.
We keep only a one-way hash of your sign-in id so welcome credits cannot be claimed twice; it cannot identify you.
Purchase records may be retained where the law requires.</p></body></html>"""


@router.get("/account-deletion", response_class=HTMLResponse, include_in_schema=False)
async def deletion_page() -> str:
    return DELETION_PAGE.replace("{email}", settings.support_email)

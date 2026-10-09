from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import FoodLog, StepsDaily, User, WeightLog
from app.routers.profile import TargetsOut, effective_targets, require_profile

router = APIRouter(tags=["progress"])


class ProgressOut(BaseModel):
    days: int
    calories: list[dict]
    protein: list[dict]
    steps: list[dict]
    weights: list[dict]
    streak_days: int
    avg_kcal: float
    avg_protein_g: float
    days_logged: int
    weight_start: float | None
    weight_latest: float | None
    weight_target: float | None
    targets: TargetsOut
    estimated: bool = True


def streak(logged_days: set[date], today: date) -> int:
    """Consecutive logged days ending today, or yesterday if today has no log yet."""
    cur = today if today in logged_days else today - timedelta(days=1)
    n = 0
    while cur in logged_days:
        n += 1
        cur -= timedelta(days=1)
    return n


@router.get("/progress", response_model=ProgressOut)
async def progress(
    days: int = Query(7), today: date | None = Query(None),
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    if days not in (7, 14, 30, 90):
        raise HTTPException(422, "days must be 7, 14, 30 or 90")
    profile = await require_profile(session, user)
    today = today or date.today()  # noqa: DTZ011
    start = today - timedelta(days=days - 1)

    per_day = {
        d: (kcal, protein)
        for d, kcal, protein in (await session.execute(
            select(FoodLog.logged_on, func.sum(FoodLog.kcal), func.sum(FoodLog.protein_g))
            .where(FoodLog.user_id == user.id, FoodLog.logged_on >= start, FoodLog.logged_on <= today)
            .group_by(FoodLog.logged_on)
        )).all()
    }
    # streak can reach back past the chart range, so look at every day with a log up to today
    logged_days = set((await session.execute(
        select(FoodLog.logged_on).where(FoodLog.user_id == user.id, FoodLog.logged_on <= today).distinct()
    )).scalars())
    steps_rows = (await session.execute(
        select(StepsDaily.day, StepsDaily.steps)
        .where(StepsDaily.user_id == user.id, StepsDaily.day >= start, StepsDaily.day <= today).order_by(StepsDaily.day)
    )).all()
    weight_rows = (await session.execute(
        select(WeightLog.logged_on, WeightLog.kg)
        .where(WeightLog.user_id == user.id, WeightLog.logged_on >= start, WeightLog.logged_on <= today)
        .order_by(WeightLog.logged_on)
    )).all()

    every_day = [start + timedelta(days=i) for i in range(days)]
    calories = [{"day": d, "kcal": round(per_day.get(d, (0, 0))[0] or 0, 1)} for d in every_day]
    protein = [{"day": d, "protein_g": round(per_day.get(d, (0, 0))[1] or 0, 1)} for d in every_day]
    n_logged = len(per_day)
    return ProgressOut(
        days=days,
        calories=calories,
        protein=protein,
        steps=[{"day": d, "steps": n} for d, n in steps_rows],
        weights=[{"day": d, "kg": k} for d, k in weight_rows],
        streak_days=streak(logged_days, today),
        avg_kcal=round(sum(c["kcal"] for c in calories) / n_logged, 1) if n_logged else 0,
        avg_protein_g=round(sum(p["protein_g"] for p in protein) / n_logged, 1) if n_logged else 0,
        days_logged=n_logged,
        weight_start=weight_rows[0][1] if weight_rows else None,
        weight_latest=weight_rows[-1][1] if weight_rows else None,
        weight_target=profile.target_weight_kg,
        targets=await effective_targets(session, user.id, profile),
    )

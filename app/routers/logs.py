from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import FoodLog, StepsDaily, User, WaterLog, WeightLog
from app.routers.profile import TargetsOut, effective_targets, require_profile

router = APIRouter(tags=["logs"])
MealType = Literal["breakfast", "lunch", "snack", "dinner"]


class FoodIn(BaseModel):
    logged_on: date
    meal_type: MealType
    name: str = Field(min_length=1, max_length=120)
    quantity: str = Field(default="", max_length=60)
    kcal: float = Field(ge=0, le=5000)
    protein_g: float = Field(default=0, ge=0, le=500)
    carbs_g: float = Field(default=0, ge=0, le=1000)
    fat_g: float = Field(default=0, ge=0, le=500)
    fibre_g: float = Field(default=0, ge=0, le=200)
    source: Literal["manual", "ai"] = "manual"


class FoodOut(FoodIn):
    id: str


class WaterIn(BaseModel):
    logged_on: date
    ml: int = Field(ge=1, le=3000)


class WeightIn(BaseModel):
    logged_on: date
    kg: float = Field(ge=30, le=300)


class StepsIn(BaseModel):
    day: date
    steps: int = Field(ge=0, le=200_000)


def _food(f: FoodLog) -> FoodOut:
    return FoodOut(
        id=f.id, logged_on=f.logged_on, meal_type=f.meal_type, name=f.name, quantity=f.quantity, kcal=f.kcal,
        protein_g=f.protein_g, carbs_g=f.carbs_g, fat_g=f.fat_g, fibre_g=f.fibre_g, source=f.source,
    )


@router.post("/logs/food", response_model=FoodOut, status_code=201)
async def add_food(body: FoodIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = FoodLog(user_id=user.id, **body.model_dump())
    session.add(row)
    await session.commit()
    return _food(row)


@router.delete("/logs/food/{food_id}", status_code=204)
async def delete_food(food_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(delete(FoodLog).where(FoodLog.id == food_id, FoodLog.user_id == user.id))
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.post("/logs/water", status_code=201)
async def add_water(body: WaterIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = WaterLog(user_id=user.id, **body.model_dump())
    session.add(row)
    await session.commit()
    return {"ok": True, "id": row.id}


@router.delete("/logs/water/{water_id}", status_code=204)
async def delete_water(water_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(delete(WaterLog).where(WaterLog.id == water_id, WaterLog.user_id == user.id))
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.put("/logs/weight")
async def put_weight(body: WeightIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    stmt = pg_insert(WeightLog).values(user_id=user.id, logged_on=body.logged_on, kg=body.kg)
    stmt = stmt.on_conflict_do_update(index_elements=["user_id", "logged_on"], set_={"kg": body.kg})
    await session.execute(stmt)
    await session.commit()
    return {"ok": True}


@router.put("/logs/steps")
async def put_steps(body: StepsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    stmt = pg_insert(StepsDaily).values(user_id=user.id, day=body.day, steps=body.steps)
    stmt = stmt.on_conflict_do_update(index_elements=["user_id", "day"], set_={"steps": body.steps})
    await session.execute(stmt)
    await session.commit()
    return {"ok": True}


class Totals(BaseModel):
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fibre_g: float


class WaterEntry(BaseModel):
    id: str
    ml: int
    logged_at: datetime


class DayOut(BaseModel):
    day: date
    foods: list[FoodOut]
    totals: Totals
    water_ml: int
    water_entries: list[WaterEntry]
    steps: int | None  # as reported by the device
    weight_kg: float | None
    targets: TargetsOut
    estimated: bool = True


@router.get("/day", response_model=DayOut)
async def get_day(day: date, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    foods = list((await session.execute(
        select(FoodLog).where(FoodLog.user_id == user.id, FoodLog.logged_on == day).order_by(FoodLog.created_at)
    )).scalars())
    water_rows = list((await session.execute(
        select(WaterLog).where(WaterLog.user_id == user.id, WaterLog.logged_on == day).order_by(WaterLog.created_at)
    )).scalars())
    steps = (await session.execute(
        select(StepsDaily.steps).where(StepsDaily.user_id == user.id, StepsDaily.day == day)
    )).scalar_one_or_none()
    weight = (await session.execute(
        select(WeightLog.kg).where(WeightLog.user_id == user.id, WeightLog.logged_on == day)
    )).scalar_one_or_none()
    totals = Totals(
        kcal=sum(f.kcal for f in foods), protein_g=sum(f.protein_g for f in foods),
        carbs_g=sum(f.carbs_g for f in foods), fat_g=sum(f.fat_g for f in foods), fibre_g=sum(f.fibre_g for f in foods),
    )
    return DayOut(
        day=day, foods=[_food(f) for f in foods], totals=totals, water_ml=sum(w.ml for w in water_rows),
        water_entries=[WaterEntry(id=w.id, ml=w.ml, logged_at=w.created_at) for w in water_rows],
        steps=steps, weight_kg=weight, targets=await effective_targets(session, user.id, profile),
    )


def _today(today: date | None) -> date:
    return today or date.today()  # noqa: DTZ011


@router.get("/weights")
async def weights(
    days: int = Query(90, ge=1, le=730), today: date | None = None,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    since = _today(today) - timedelta(days=days - 1)
    rows = (await session.execute(
        select(WeightLog.logged_on, WeightLog.kg).where(WeightLog.user_id == user.id, WeightLog.logged_on >= since).order_by(WeightLog.logged_on)
    )).all()
    return [{"day": d, "kg": k} for d, k in rows]


@router.get("/steps")
async def steps_history(
    days: int = Query(7, ge=1, le=730), today: date | None = None,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    since = _today(today) - timedelta(days=days - 1)
    rows = (await session.execute(
        select(StepsDaily.day, StepsDaily.steps).where(StepsDaily.user_id == user.id, StepsDaily.day >= since).order_by(StepsDaily.day)
    )).all()
    return [{"day": d, "steps": n} for d, n in rows]

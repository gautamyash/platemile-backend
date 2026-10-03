from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import Meal, MealType, PlanMeal
from app.db import get_session
from app.deps import current_user
from app.models import MealPlanEntry, User

router = APIRouter(prefix="/plans", tags=["plans"])

MEAL_ORDER = {"breakfast": 0, "lunch": 1, "snack": 2, "dinner": 3}
MAX_RANGE_DAYS = 93


class PlanDayOut(BaseModel):
    date: date
    meals: list[PlanMeal]


class PlansOut(BaseModel):
    days: list[PlanDayOut]


class LoggedIn(BaseModel):
    logged: bool


def plan_meal(e: MealPlanEntry) -> PlanMeal:
    return PlanMeal(**{**e.meal, "meal_type": e.meal_type, "logged": e.logged})


def group_days(entries: list[MealPlanEntry]) -> list[PlanDayOut]:
    by_day: dict[date, list[MealPlanEntry]] = {}
    for e in entries:
        by_day.setdefault(e.plan_date, []).append(e)
    return [
        PlanDayOut(date=d, meals=[plan_meal(e) for e in sorted(es, key=lambda e: MEAL_ORDER[e.meal_type])])
        for d, es in sorted(by_day.items())
    ]


def check_range(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(422, "'to' must not be before 'from'")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, f"Date range is limited to {MAX_RANGE_DAYS} days")


async def entries_between(session: AsyncSession, user_id: str, start: date, end: date) -> list[MealPlanEntry]:
    return list((await session.execute(
        select(MealPlanEntry).where(
            MealPlanEntry.user_id == user_id, MealPlanEntry.plan_date >= start, MealPlanEntry.plan_date <= end
        ).order_by(MealPlanEntry.plan_date)
    )).scalars())


@router.get("", response_model=PlansOut)
async def get_plans(
    from_: date = Query(alias="from"), to: date = Query(),
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    check_range(from_, to)
    return PlansOut(days=group_days(await entries_between(session, user.id, from_, to)))


@router.put("/{plan_date}/meals/{meal_type}", response_model=PlanMeal)
async def put_plan_meal(
    plan_date: date, meal_type: MealType, body: Meal,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    data = body.model_dump()
    stmt = pg_insert(MealPlanEntry).values(user_id=user.id, plan_date=plan_date, meal_type=meal_type, meal=data, logged=False)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "plan_date", "meal_type"], set_={"meal": data, "logged": False}
    )
    await session.execute(stmt)
    await session.commit()
    return PlanMeal(**data, meal_type=meal_type, logged=False)


@router.post("/{plan_date}/meals/{meal_type}/logged", status_code=204)
async def set_logged(
    plan_date: date, meal_type: MealType, body: LoggedIn,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        update(MealPlanEntry)
        .where(MealPlanEntry.user_id == user.id, MealPlanEntry.plan_date == plan_date, MealPlanEntry.meal_type == meal_type)
        .values(logged=body.logged)
    )
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No meal planned in that slot")


@router.delete("/{plan_date}", status_code=204)
async def delete_plan_day(plan_date: date, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(MealPlanEntry).where(MealPlanEntry.user_id == user.id, MealPlanEntry.plan_date == plan_date))
    await session.commit()


def date_range(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]

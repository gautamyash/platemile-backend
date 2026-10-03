from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import Food, FoodLog, User

router = APIRouter(prefix="/foods", tags=["foods"])


class FoodHit(BaseModel):
    id: int
    name: str
    serving: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fibre_g: float


class RecentFood(BaseModel):
    name: str
    serving: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fibre_g: float


@router.get("/search", response_model=list[FoodHit])
async def search_foods(
    q: str = Query("", max_length=60), limit: int = Query(20, ge=1, le=50),
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
):
    q = q.strip()
    stmt = select(Food)
    if q:
        stmt = stmt.where(or_(Food.name.icontains(q, autoescape=True), Food.aliases.icontains(q.lower(), autoescape=True)))
        # name prefix matches first, then other name matches, then alias-only matches
        rank = case(
            (func.lower(Food.name).startswith(q.lower(), autoescape=True), 0),
            (Food.name.icontains(q, autoescape=True), 1),
            else_=2,
        )
        stmt = stmt.order_by(rank, Food.popularity, Food.name)
    else:
        stmt = stmt.order_by(Food.popularity, Food.name)
    rows = (await session.execute(stmt.limit(limit))).scalars()
    return [
        FoodHit(id=f.id, name=f.name, serving=f.serving, kcal=f.kcal, protein_g=f.protein_g, carbs_g=f.carbs_g,
                fat_g=f.fat_g, fibre_g=f.fibre_g)
        for f in rows
    ]


@router.get("/recent", response_model=list[RecentFood])
async def recent_foods(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(FoodLog).where(FoodLog.user_id == user.id).order_by(FoodLog.created_at.desc(), FoodLog.id).limit(200)
    )).scalars()
    seen: set[str] = set()
    out: list[RecentFood] = []
    for f in rows:
        key = f.name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(RecentFood(name=f.name, serving=f.quantity, kcal=f.kcal, protein_g=f.protein_g, carbs_g=f.carbs_g,
                              fat_g=f.fat_g, fibre_g=f.fibre_g))
        if len(out) == 8:
            break
    return out

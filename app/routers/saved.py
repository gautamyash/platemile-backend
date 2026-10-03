from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import Meal
from app.db import get_session
from app.deps import current_user
from app.models import SavedMeal, User

router = APIRouter(prefix="/saved", tags=["saved"])
MAX_SAVED = 200


class SavedIn(BaseModel):
    meal: Meal


class SavedOut(BaseModel):
    id: str
    meal: Meal
    created_at: datetime


def _out(s: SavedMeal) -> SavedOut:
    return SavedOut(id=s.id, meal=Meal(**s.meal), created_at=s.created_at)


async def _existing(session: AsyncSession, user_id: str, name: str) -> SavedMeal | None:
    return (await session.execute(select(SavedMeal).where(SavedMeal.user_id == user_id, SavedMeal.name == name))).scalar_one_or_none()


@router.get("", response_model=list[SavedOut])
async def list_saved(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(SavedMeal).where(SavedMeal.user_id == user.id).order_by(SavedMeal.created_at.desc(), SavedMeal.id)
    )).scalars()
    return [_out(s) for s in rows]


@router.post("", response_model=SavedOut, status_code=201)
async def save_meal(body: SavedIn, response: Response, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    found = await _existing(session, user.id, body.meal.name)
    if found is None:
        count = len((await session.execute(select(SavedMeal.id).where(SavedMeal.user_id == user.id))).all())
        if count >= MAX_SAVED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Saved meals limit reached")
        row = SavedMeal(user_id=user.id, name=body.meal.name, meal=body.meal.model_dump())
        session.add(row)
        try:
            await session.commit()
            return _out(row)
        except IntegrityError:  # a parallel request saved the same name first
            await session.rollback()
            found = await _existing(session, user.id, body.meal.name)
    response.status_code = status.HTTP_200_OK
    return _out(found)


@router.delete("/{saved_id}", status_code=204)
async def delete_saved(saved_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(delete(SavedMeal).where(SavedMeal.id == saved_id, SavedMeal.user_id == user.id))
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

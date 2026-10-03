from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import credits
from app.db import get_session
from app.deps import current_user
from app.models import User

router = APIRouter(tags=["credits"])


class LedgerRow(BaseModel):
    delta: int
    reason: str
    created_at: datetime


class CreditsOut(BaseModel):
    balance: int
    costs: dict[str, int]
    history: list[LedgerRow]


@router.get("/credits", response_model=CreditsOut)
async def get_credits(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await credits.history(session, user.id)
    return CreditsOut(
        balance=await credits.balance(session, user.id),
        costs=credits.COSTS,
        history=[LedgerRow(delta=r.delta, reason=r.reason, created_at=r.created_at) for r in rows],
    )

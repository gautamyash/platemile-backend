"""Credits are backend-controlled: reserve before the AI call, refund if it fails.

The ledger is append-only; balance = sum(delta). Reserve takes a row lock on the user so two
parallel requests cannot both spend the last credit.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditLedger, User

COSTS = {
    "find_meal": 1,
    "replace_meal": 1,
    "coach_message": 1,
    "grocery_list": 1,
    "plan_1d": 1,
    "plan_3d": 3,
    "plan_7d": 5,
}


class InsufficientCredits(Exception):
    pass


async def balance(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(CreditLedger.user_id == user_id)
    )
    return int(result.scalar_one())


async def grant(session: AsyncSession, user_id: str, amount: int, reason: str) -> None:
    session.add(CreditLedger(user_id=user_id, delta=amount, reason=reason))


async def reserve(session: AsyncSession, user_id: str, intent: str, request_id: str) -> int:
    """Deducts the cost. Caller must commit. Raises InsufficientCredits."""
    cost = COSTS[intent]
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
    if await balance(session, user_id) < cost:
        raise InsufficientCredits(intent)
    session.add(CreditLedger(user_id=user_id, delta=-cost, reason="reserve", request_id=request_id))
    return cost


async def refund(session: AsyncSession, user_id: str, amount: int, request_id: str) -> None:
    """Refunds a reserve at most once per request."""
    existing = await session.execute(
        select(CreditLedger.id).where(CreditLedger.request_id == request_id, CreditLedger.reason == "refund")
    )
    if existing.first() is None:
        session.add(CreditLedger(user_id=user_id, delta=amount, reason="refund", request_id=request_id))


async def history(session: AsyncSession, user_id: str, limit: int = 50) -> list[CreditLedger]:
    rows = await session.execute(
        select(CreditLedger).where(CreditLedger.user_id == user_id).order_by(CreditLedger.id.desc()).limit(limit)
    )
    return list(rows.scalars())

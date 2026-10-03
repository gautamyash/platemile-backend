import json
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import Report, User
from app.ratelimit import limit

router = APIRouter(prefix="/reports", tags=["reports"])
MAX_CONTEXT_CHARS = 4000


class ReportIn(BaseModel):
    kind: Literal["ai_answer", "bug", "other"]
    reason: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=500)
    context: dict = Field(default_factory=dict)

    @field_validator("context")
    @classmethod
    def small_context(cls, v: dict) -> dict:
        if len(json.dumps(v, default=str)) > MAX_CONTEXT_CHARS:
            raise ValueError("context is too large")
        return v


@router.post("", status_code=201, dependencies=[limit("reports", 10, 3600)])
async def create_report(body: ReportIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = Report(user_id=user.id, **body.model_dump())
    session.add(row)
    await session.commit()
    return {"id": row.id}

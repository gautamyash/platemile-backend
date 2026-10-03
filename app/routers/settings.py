import copy
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import User, UserSettings

router = APIRouter(tags=["settings"])

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ReminderTimes(BaseModel):
    breakfast: str = Field(default="08:30", pattern=HHMM)
    lunch: str = Field(default="13:00", pattern=HHMM)
    dinner: str = Field(default="20:00", pattern=HHMM)


class Notifications(BaseModel):
    meal_reminders: bool = True
    water_reminders: bool = True
    weigh_in: bool = False
    weekly_summary: bool = True
    reminder_times: ReminderTimes = Field(default_factory=ReminderTimes)


class SettingsOut(BaseModel):
    notifications: Notifications = Field(default_factory=Notifications)
    units: Literal["metric", "imperial"] = "metric"
    theme: Literal["system", "light", "dark"] = "system"
    language: Literal["en", "hi", "hinglish"] = "en"


class ReminderTimesPatch(BaseModel):
    breakfast: str | None = Field(default=None, pattern=HHMM)
    lunch: str | None = Field(default=None, pattern=HHMM)
    dinner: str | None = Field(default=None, pattern=HHMM)


class NotificationsPatch(BaseModel):
    meal_reminders: bool | None = None
    water_reminders: bool | None = None
    weigh_in: bool | None = None
    weekly_summary: bool | None = None
    reminder_times: ReminderTimesPatch | None = None


class SettingsPatch(BaseModel):
    notifications: NotificationsPatch | None = None
    units: Literal["metric", "imperial"] | None = None
    theme: Literal["system", "light", "dark"] | None = None
    language: Literal["en", "hi", "hinglish"] | None = None


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@router.get("/settings", response_model=SettingsOut)
async def get_settings(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = await session.get(UserSettings, user.id)
    return SettingsOut.model_validate(row.data if row else {})


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsPatch, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = await session.get(UserSettings, user.id)
    current = SettingsOut.model_validate(row.data if row else {}).model_dump()
    merged = SettingsOut.model_validate(_merge(current, body.model_dump(exclude_none=True)))
    if row is None:
        session.add(UserSettings(user_id=user.id, data=merged.model_dump()))
    else:
        row.data = merged.model_dump()  # new dict object, so the JSON column change is detected
    await session.commit()
    return merged

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import TargetOverride, User, UserProfile
from app.nutrition import (
    MIN_ADULT_AGE,
    Targets,
    age_from_birth_year,
    calculate_targets,
    calorie_floor,
    check_override,
)

router = APIRouter(tags=["profile"])

Goal = Literal["lose_weight", "build_muscle", "maintain", "eat_healthier"]
Diet = Literal["veg", "non_veg", "eggetarian", "vegan"]
Sex = Literal["male", "female"]
Activity = Literal["sedentary", "light", "active", "very_active"]


class Restrictions(BaseModel):
    allergies: list[str] = Field(default_factory=list, max_length=20)
    dislikes: list[str] = Field(default_factory=list, max_length=30)
    cuisines: list[str] = Field(default_factory=list, max_length=10)


class ProfileIn(BaseModel):
    goal: Goal
    diet_type: Diet
    sex: Sex
    birth_year: int = Field(ge=1900)
    height_cm: float = Field(ge=100, le=250)
    weight_kg: float = Field(ge=30, le=300)
    target_weight_kg: float | None = Field(default=None, ge=30, le=300)
    activity_level: Activity
    meals_per_day: int = Field(default=3, ge=2, le=6)
    restrictions: Restrictions = Field(default_factory=Restrictions)
    health_consent: bool = False

    @model_validator(mode="after")
    def adult_only(self):
        if age_from_birth_year(self.birth_year) < MIN_ADULT_AGE:
            raise ValueError("PlateMile is for adults (18+).")
        return self


class ProfileOut(BaseModel):
    goal: Goal
    diet_type: Diet
    sex: Sex
    birth_year: int
    height_cm: float
    weight_kg: float
    target_weight_kg: float | None
    activity_level: Activity
    meals_per_day: int
    restrictions: Restrictions


class TargetsOut(BaseModel):
    bmr: int
    tdee: int
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    fibre_g: int
    water_ml: int
    steps_goal: int
    notes: list[str]
    overridden: bool = False
    estimated: bool = True


def targets_for(profile: UserProfile) -> Targets:
    return calculate_targets(
        sex=profile.sex,
        weight_kg=profile.weight_kg,
        height_cm=profile.height_cm,
        age=age_from_birth_year(profile.birth_year),
        activity_level=profile.activity_level,
        goal=profile.goal,
    )


def _out(p: UserProfile) -> ProfileOut:
    return ProfileOut(
        goal=p.goal, diet_type=p.diet_type, sex=p.sex, birth_year=p.birth_year, height_cm=p.height_cm,
        weight_kg=p.weight_kg, target_weight_kg=p.target_weight_kg, activity_level=p.activity_level,
        meals_per_day=p.meals_per_day, restrictions=Restrictions(**(p.restrictions or {})),
    )


async def require_profile(session: AsyncSession, user: User) -> UserProfile:
    profile = await session.get(UserProfile, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Complete your profile first")
    return profile


@router.put("/profile", response_model=ProfileOut)
async def put_profile(body: ProfileIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if user.health_consent_at is None:
        if not body.health_consent:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consent to health data processing is required")
        from datetime import datetime, timezone

        user.health_consent_at = datetime.now(timezone.utc)
    data = body.model_dump(exclude={"health_consent"})
    profile = await session.get(UserProfile, user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id, **data)
        session.add(profile)
    else:
        for k, v in data.items():
            setattr(profile, k, v)
    await session.commit()
    return _out(profile)


@router.get("/profile", response_model=ProfileOut)
async def get_profile(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return _out(await require_profile(session, user))


async def effective_targets(session: AsyncSession, user_id: str, profile: UserProfile) -> TargetsOut:
    """Computed targets, replaced by the user's saved override where one exists."""
    base = targets_for(profile)
    out = TargetsOut(**base.__dict__)
    ov = await session.get(TargetOverride, user_id)
    if ov is None:
        return out
    out.kcal, out.protein_g, out.carbs_g, out.fat_g = ov.kcal, ov.protein_g, ov.carbs_g, ov.fat_g
    out.fibre_g = max(round(ov.kcal / 1000 * 14), 20)
    if ov.water_ml is not None:
        out.water_ml = ov.water_ml
    if ov.steps_goal is not None:
        out.steps_goal = ov.steps_goal
    out.overridden = True
    return out


class TargetsIn(BaseModel):
    kcal: int = Field(ge=1, le=6000)
    protein_g: int = Field(ge=0, le=1000)
    carbs_g: int = Field(ge=0, le=1500)
    fat_g: int = Field(ge=0, le=600)
    water_ml: int | None = Field(default=None, ge=500, le=10000)
    steps_goal: int | None = Field(default=None, ge=1000, le=100_000)


@router.get("/targets", response_model=TargetsOut)
async def get_targets(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await effective_targets(session, user.id, await require_profile(session, user))


@router.put("/targets", response_model=TargetsOut)
async def put_targets(body: TargetsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    problem = check_override(sex=profile.sex, kcal=body.kcal, protein_g=body.protein_g, carbs_g=body.carbs_g, fat_g=body.fat_g)
    if problem:
        raise HTTPException(
            422,
            {"code": "unsafe", "message": problem, "min_kcal": calorie_floor(profile.sex)},
        )
    ov = await session.get(TargetOverride, user.id)
    if ov is None:
        session.add(TargetOverride(user_id=user.id, **body.model_dump()))
    else:
        for k, v in body.model_dump().items():
            setattr(ov, k, v)
    await session.commit()
    return await effective_targets(session, user.id, profile)


@router.delete("/targets/override", response_model=TargetsOut)
async def delete_targets_override(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    await session.execute(delete(TargetOverride).where(TargetOverride.user_id == user.id))
    await session.commit()
    return await effective_targets(session, user.id, profile)

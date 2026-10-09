import logging
import random
import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import coach as coach_engine
from app import credits, grocery, meal_engine
from app.ai import gemini, prompts, safety
from app.ai.schemas import (
    AiPlan,
    AiPlanDay,
    CoachReply,
    DailyPlan,
    GroceryGroup,
    GroceryList,
    Meal,
    MealResults,
    PlannedMeal,
)
from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.models import AiRequest, FoodLog, MealPlanEntry, User
from app.ratelimit import limit
from app.routers.plans import (
    PlanDayOut,
    date_range,
    entries_between,
    group_days,
)
from app.routers.profile import effective_targets, require_profile

log = logging.getLogger("ai")
router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[limit("ai", 15, 60)])

MealType = Literal["breakfast", "lunch", "snack", "dinner"]
MAX_GROCERY_DAYS = 14
SLOTS = {3: ["breakfast", "lunch", "dinner"], 4: ["breakfast", "lunch", "snack", "dinner"], 5: ["breakfast", "lunch", "snack", "dinner"]}
Tag = Literal["high_protein", "light", "quick", "spicy", "comfort", "budget", "low_oil", "high_fibre"]
CoachId = Literal[
    "what_to_eat", "under_400", "protein_help", "replace_dinner", "todays_diet", "analyze_week",
    "hydration", "low_energy", "plateau", "eating_out", "motivation",
]


class FindMealIn(BaseModel):
    meal_type: MealType
    tags: list[Tag] = Field(default_factory=list, max_length=4)
    max_minutes: Literal[10, 15, 20, 30, 45, 60] = 30
    max_kcal: int | None = Field(default=None, ge=100, le=1200)
    ingredients_at_home: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=8
    )
    food_type: Literal["veg", "non_veg", "egg", "vegan", "jain"] | None = None
    cuisine: Literal["south_indian", "north_indian"] | None = None


class MealsOut(BaseModel):
    meals: list[Meal]
    credits_left: int
    estimated: bool = True


class PlanOut(BaseModel):
    plan: DailyPlan
    credits_left: int
    estimated: bool = True


class PlanIn(BaseModel):
    start_date: date
    days: Literal[1, 3, 7]
    meals_per_day: Literal[3, 4, 5]


class PlanDaysOut(BaseModel):
    plan_days: list[PlanDayOut]
    credits_left: int
    estimated: bool = True


class ReplaceIn(BaseModel):
    plan_date: date | None = None
    meal_type: MealType
    current_name: str = Field(min_length=1, max_length=100)
    reason: Literal["dont_like", "no_time", "missing_ingredient", "lighter", "more_protein"]


class ReplaceOut(BaseModel):
    meals: list[Meal]
    credits_left: int
    estimated: bool = True


class GroceryIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date

    @model_validator(mode="after")
    def in_range(self):
        if self.to < self.from_ or (self.to - self.from_).days >= MAX_GROCERY_DAYS:
            raise ValueError(f"'to' must be on or after 'from', within {MAX_GROCERY_DAYS} days")
        return self


class GroceryOut(BaseModel):
    groups: list[GroceryGroup]
    credits_left: int


class CoachIn(BaseModel):
    prompt_id: CoachId
    meal_type: MealType | None = None  # which meal the user is asking about (defaults by time of day on the client)
    today: date | None = None  # the user's local date, for "kcal left today" and the weekly review


class CoachOut(BaseModel):
    message: str
    credits_left: int
    meals: list[Meal] = Field(default_factory=list)
    plan: list[PlannedMeal] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    estimated: bool = True
    disclaimer: str = "General wellness information, not medical advice."


async def _run(session: AsyncSession, user: User, intent: str, payload: dict, call):
    """Reserve credits, run the model call, refund on any failure. Returns (result, credits_left)."""
    request_id = str(uuid.uuid4())
    try:
        cost = await credits.reserve(session, user.id, intent, request_id)
    except credits.InsufficientCredits:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Not enough credits")
    session.add(AiRequest(id=request_id, user_id=user.id, intent=intent, input_json=payload, status="pending", credits=cost))
    await session.commit()  # credits are held before the (slow) model call

    try:
        result = await call()
    except meal_engine.NoMealFound:
        log.info("ai %s: no recipe matches the request", intent)
        await credits.refund(session, user.id, cost, request_id)
        req = await session.get(AiRequest, request_id)
        req.status = "failed"
        await session.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No meals match these choices. Try a higher calorie limit or fewer filters. Your credit was returned.")
    except (gemini.AiUnavailable, safety_blocked) as exc:
        log.warning("ai %s failed: %s", intent, type(exc).__name__)
        await credits.refund(session, user.id, cost, request_id)
        req = await session.get(AiRequest, request_id)
        req.status = "failed"
        await session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "We couldn't prepare that right now. Your credit was returned.")
    req = await session.get(AiRequest, request_id)
    req.status = "done"
    await session.commit()
    return result, await credits.balance(session, user.id)


class safety_blocked(Exception):
    pass


def _llm() -> bool:
    return settings.ai_mode == "llm"


def _slots_for_profile(profile) -> list[str]:
    return list(SLOTS[4]) if profile.meals_per_day >= 4 else list(SLOTS[3])


async def _rng(session: AsyncSession, user: User, day: date) -> random.Random:
    """Seeded from user id + date + number of earlier AI requests: reproducible for a given history, different for each request."""
    n = (await session.execute(select(func.count()).select_from(AiRequest).where(AiRequest.user_id == user.id))).scalar_one()
    return random.Random(f"{user.id}|{day.isoformat()}|{n}")


def _guard(meals, profile) -> None:
    """Engine output must pass the same SafetyGuard check as model output."""
    r = profile.restrictions or {}
    if any(safety.violations(m, profile.diet_type, r.get("allergies", []), r.get("dislikes", [])) for m in meals):
        raise safety_blocked()


# ------------------------------------------------------------------------------------------ find meal
@router.post("/find-meal", response_model=MealsOut)
async def find_meal(body: FindMealIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    targets = await effective_targets(session, user.id, profile)
    r = profile.restrictions or {}
    rng = await _rng(session, user, date.today())  # noqa: DTZ011

    async def call() -> list[Meal]:
        if _llm():
            out = await gemini.generate_json(prompts.SYSTEM, prompts.find_meal_prompt(profile, targets, body.meal_type, body.tags, body.max_minutes, body.max_kcal, body.ingredients_at_home), MealResults)
            ok = safety.filter_meals(out.meals, profile.diet_type, r.get("allergies", []), r.get("dislikes", []))
            if body.max_kcal:
                ok = [m for m in ok if m.kcal <= body.max_kcal * 1.1]  # small tolerance: values are estimates anyway
        else:
            ok = meal_engine.find_meals(
                profile, targets.kcal, body.meal_type, rng, tags=body.tags, max_minutes=body.max_minutes,
                max_kcal=body.max_kcal, home=body.ingredients_at_home, slots=_slots_for_profile(profile),
                food_type=body.food_type, cuisine=body.cuisine,
            )
            _guard(ok, profile)
        if not ok:
            raise safety_blocked()
        return ok

    meals, left = await _run(session, user, "find_meal", body.model_dump(), call)
    return MealsOut(meals=meals, credits_left=left)


# ------------------------------------------------------------------------------------------ legacy one-day plan
@router.post("/daily-plan", response_model=PlanOut)
async def daily_plan(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    targets = await effective_targets(session, user.id, profile)
    r = profile.restrictions or {}
    rng = await _rng(session, user, date.today())  # noqa: DTZ011

    async def call() -> DailyPlan:
        if _llm():
            out = await gemini.generate_json(prompts.SYSTEM, prompts.daily_plan_prompt(profile, targets), DailyPlan)
            ok = [m for m in out.meals if not safety.violations(m, profile.diet_type, r.get("allergies", []), r.get("dislikes", []))]
            if len(ok) < len(out.meals):  # a plan with a removed meal would be misleading; reject whole plan
                raise safety_blocked()
            return out
        slots = {2: ["lunch", "dinner"], 3: SLOTS[3]}.get(profile.meals_per_day, SLOTS[4])
        day = meal_engine.build_plan(profile, targets.kcal, 1, list(slots), rng)[0]
        _guard([m for _, m in day], profile)
        return DailyPlan(meals=[meal_engine.planned(s, m) for s, m in day])

    plan, left = await _run(session, user, "plan_1d", {}, call)
    return PlanOut(plan=plan, credits_left=left)


# ------------------------------------------------------------------------------------------ multi-day plan
@router.post("/plan", response_model=PlanDaysOut)
async def plan(body: PlanIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    targets = await effective_targets(session, user.id, profile)
    r = profile.restrictions or {}
    slots = SLOTS[body.meals_per_day]  # 5 meals/day still maps to the 4 slots a day can hold
    rng = await _rng(session, user, body.start_date)

    async def call() -> AiPlan:
        if not _llm():
            built = meal_engine.build_plan(profile, targets.kcal, body.days, list(slots), rng)
            for day in built:
                _guard([m for _, m in day], profile)
            return AiPlan(days=[AiPlanDay(meals=[meal_engine.planned(s, m) for s, m in day]) for day in built])
        out = await gemini.generate_json(prompts.SYSTEM, prompts.plan_prompt(profile, targets, body.start_date, body.days, slots), AiPlan)
        if len(out.days) != body.days:
            raise safety_blocked()
        for day in out.days:
            if sorted(m.meal_type for m in day.meals) != sorted(slots):
                raise safety_blocked()
            if any(safety.violations(m, profile.diet_type, r.get("allergies", []), r.get("dislikes", [])) for m in day.meals):
                raise safety_blocked()  # a plan with a removed meal would be misleading; reject the whole plan
        return out

    out, left = await _run(session, user, f"plan_{body.days}d", body.model_dump(mode="json"), call)
    dates = date_range(body.start_date, body.days)
    await session.execute(delete(MealPlanEntry).where(MealPlanEntry.user_id == user.id, MealPlanEntry.plan_date.in_(dates)))
    for d, day in zip(dates, out.days):
        for m in day.meals:
            data = Meal(**m.model_dump(exclude={"meal_type"})).model_dump()
            session.add(MealPlanEntry(user_id=user.id, plan_date=d, meal_type=m.meal_type, meal=data, logged=False))
    await session.commit()
    entries = await entries_between(session, user.id, dates[0], dates[-1])
    return PlanDaysOut(plan_days=group_days(entries), credits_left=left)


# ------------------------------------------------------------------------------------------ replace meal
@router.post("/replace-meal", response_model=ReplaceOut)
async def replace_meal(body: ReplaceIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    targets = await effective_targets(session, user.id, profile)
    r = profile.restrictions or {}
    others: list[str] = []
    current = meal_engine.CurrentMeal(name=body.current_name)
    if body.plan_date:
        rows = await entries_between(session, user.id, body.plan_date, body.plan_date)
        others = [e.meal.get("name", "") for e in rows if e.meal_type != body.meal_type]
        for e in rows:
            if e.meal_type == body.meal_type and e.meal.get("name", "").strip().lower() == body.current_name.strip().lower():
                mm = e.meal
                current = meal_engine.CurrentMeal(
                    name=body.current_name, kcal=mm.get("kcal"), protein_g=mm.get("protein_g"), prep_minutes=mm.get("prep_minutes"),
                )
    rng = await _rng(session, user, body.plan_date or date.today())  # noqa: DTZ011

    async def call() -> list[Meal]:
        if _llm():
            out = await gemini.generate_json(
                prompts.SYSTEM,
                prompts.replace_meal_prompt(profile, targets, body.meal_type, body.current_name, body.reason, others),
                MealResults,
            )
            ok = safety.filter_meals(out.meals, profile.diet_type, r.get("allergies", []), r.get("dislikes", []))
            ok = [m for m in ok if m.name.strip().lower() != body.current_name.strip().lower()][:3]
        else:
            ok = meal_engine.replace_meals(
                profile, targets.kcal, body.meal_type, rng, body.reason, current, exclude_names=others,
                slots=_slots_for_profile(profile),
            )
            _guard(ok, profile)
        if not ok:
            raise safety_blocked()
        return ok

    meals, left = await _run(session, user, "replace_meal", body.model_dump(mode="json"), call)
    return ReplaceOut(meals=meals, credits_left=left)


# ------------------------------------------------------------------------------------------ grocery list
@router.post("/grocery-list", response_model=GroceryOut)
async def grocery_list(body: GroceryIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    targets = await effective_targets(session, user.id, profile)
    r = profile.restrictions or {}
    entries = await entries_between(session, user.id, body.from_, body.to)
    if not entries:
        raise HTTPException(status.HTTP_409_CONFLICT, "No meal plan found for those dates")
    meals = [(e.plan_date.isoformat(), e.meal_type, e.meal.get("name", ""), list(e.meal.get("ingredients", []))) for e in entries]

    async def call() -> GroceryList:
        if _llm():
            out = await gemini.generate_json(prompts.SYSTEM, prompts.grocery_prompt(profile, targets, meals), GroceryList)
        else:
            groups = grocery.build_grocery([ing for _, _, _, ing in meals])
            if not groups:
                raise safety_blocked()
            out = GroceryList(groups=groups)
        if safety.grocery_violations(out.groups, profile.diet_type, r.get("allergies", [])):
            raise safety_blocked()
        return out

    out, left = await _run(session, user, "grocery_list", {"from": body.from_.isoformat(), "to": body.to.isoformat()}, call)
    return GroceryOut(groups=out.groups, credits_left=left)


@router.post("/coach", response_model=CoachOut)
async def coach(body: CoachIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    profile = await require_profile(session, user)
    targets = await effective_targets(session, user.id, profile)
    today = body.today or date.today()  # noqa: DTZ011
    pid = body.prompt_id
    slots = _slots_for_profile(profile)
    rng = await _rng(session, user, today)

    async def logs_since(start: date) -> list[coach_engine.DayLog]:
        rows = (await session.execute(
            select(FoodLog.logged_on, func.sum(FoodLog.kcal), func.sum(FoodLog.protein_g))
            .where(FoodLog.user_id == user.id, FoodLog.logged_on >= start, FoodLog.logged_on <= today)
            .group_by(FoodLog.logged_on)
        )).all()
        return [coach_engine.DayLog(d, float(k or 0), float(p or 0)) for d, k, p in rows]

    async def call() -> coach_engine.CoachResult:
        if _llm() and pid in ("hydration", "low_energy", "plateau", "eating_out", "motivation"):
            out = await gemini.generate_json(prompts.SYSTEM, prompts.coach_prompt(profile, targets, pid), CoachReply)
            if any(c in out.message.lower() for c in safety.FORBIDDEN_CLAIMS):
                raise safety_blocked()
            return coach_engine.CoachResult(message=out.message)
        if pid in coach_engine.MEAL_PROMPTS:
            eaten = sum(d.kcal for d in await logs_since(today))
            slot = body.meal_type or "lunch"
            res = coach_engine.meal_ideas(pid, profile, targets.kcal, targets.protein_g, slot, eaten, slots, rng)
            _guard(res.meals, profile)
            return res
        if pid in coach_engine.PLAN_PROMPTS:
            res = coach_engine.todays_diet(profile, targets.kcal, slots, rng)
            _guard([m for _, m in res.plan], profile)
            return res
        if pid == "analyze_week":
            return coach_engine.analyze_week(await logs_since(today - timedelta(days=6)), targets.kcal, targets.protein_g, today)
        return coach_engine.text_reply(pid, targets.kcal, targets.protein_g)

    res, left = await _run(session, user, "coach_message", body.model_dump(mode="json"), call)
    return CoachOut(
        message=res.message, credits_left=left, meals=res.meals,
        plan=[PlannedMeal(meal_type=s_, **m.model_dump()) for s_, m in res.plan], tips=res.tips,
    )

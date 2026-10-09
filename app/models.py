import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["UserProfile | None"] = relationship(back_populates="user", uselist=False)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    goal: Mapped[str] = mapped_column(String(20))  # lose_weight, build_muscle, maintain, eat_healthier
    diet_type: Mapped[str] = mapped_column(String(20))  # veg, non_veg, eggetarian, vegan
    sex: Mapped[str] = mapped_column(String(10))
    birth_year: Mapped[int] = mapped_column(Integer)
    height_cm: Mapped[float] = mapped_column()
    weight_kg: Mapped[float] = mapped_column()
    target_weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    activity_level: Mapped[str] = mapped_column(String(20))
    meals_per_day: Mapped[int] = mapped_column(Integer, default=3)
    restrictions: Mapped[dict] = mapped_column(JSON, default=dict)  # allergies, dislikes, cuisines

    user: Mapped[User] = relationship(back_populates="profile")


class CreditLedger(Base):
    """Append-only. A user's balance is the sum of delta. Never update or delete rows."""

    __tablename__ = "credit_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40))  # welcome, reserve, refund, purchase
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiRequest(Base):
    __tablename__ = "ai_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    intent: Mapped[str] = mapped_column(String(40))
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, done, failed, blocked
    credits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FoodLog(Base):
    __tablename__ = "food_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    logged_on: Mapped[date] = mapped_column(Date, index=True)
    meal_type: Mapped[str] = mapped_column(String(12))  # breakfast, lunch, snack, dinner
    name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[str] = mapped_column(String(60), default="")
    kcal: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float, default=0)
    carbs_g: Mapped[float] = mapped_column(Float, default=0)
    fat_g: Mapped[float] = mapped_column(Float, default=0)
    fibre_g: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual, ai
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WaterLog(Base):
    __tablename__ = "water_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    logged_on: Mapped[date] = mapped_column(Date, index=True)
    ml: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WeightLog(Base):
    __tablename__ = "weight_logs"
    __table_args__ = (UniqueConstraint("user_id", "logged_on"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    logged_on: Mapped[date] = mapped_column(Date)
    kg: Mapped[float] = mapped_column(Float)


class StepsDaily(Base):
    """Device-reported steps (Health Connect). Shown as reported by the device, never as a verified figure."""

    __tablename__ = "steps_daily"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int] = mapped_column(Integer)


class DeletedIdentity(Base):
    """Salted hash of a deleted Google account id, kept only so welcome credits cannot be farmed by
    deleting and re-registering. Not reversible to the person."""

    __tablename__ = "deleted_identities"

    sub_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSettings(Base):
    """App preferences (notifications, units, theme, language) stored as one JSON document."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class TargetOverride(Base):
    """User-chosen daily targets that replace the computed ones (already safety-checked on write)."""

    __tablename__ = "target_overrides"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kcal: Mapped[int] = mapped_column(Integer)
    protein_g: Mapped[int] = mapped_column(Integer)
    carbs_g: Mapped[int] = mapped_column(Integer)
    fat_g: Mapped[int] = mapped_column(Integer)
    water_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steps_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MealPlanEntry(Base):
    __tablename__ = "meal_plan_entries"
    __table_args__ = (UniqueConstraint("user_id", "plan_date", "meal_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    meal_type: Mapped[str] = mapped_column(String(12))
    meal: Mapped[dict] = mapped_column(JSON)
    logged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedMeal(Base):
    __tablename__ = "saved_meals"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    meal: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # ai_answer, bug, other
    reason: Mapped[str] = mapped_column(String(60))
    note: Mapped[str] = mapped_column(String(500), default="")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Food(Base):
    """Seeded catalogue of common Indian foods. Values are per-serving ESTIMATES."""

    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")  # lower-case, comma separated
    serving: Mapped[str] = mapped_column(String(60))
    kcal: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float)
    fibre_g: Mapped[float] = mapped_column(Float)
    popularity: Mapped[int] = mapped_column(Integer, default=1000, index=True)  # lower = shown first


class RecipeRow(Base):
    """A meal-engine recipe. Seeded from app/meal_data on startup (insert-if-missing by name), then served from here,
    so recipes can be added or edited in the database without a deploy. `data` holds the recipe dict."""

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(60), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

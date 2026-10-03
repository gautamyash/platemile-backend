from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field, StringConstraints

MealType = Literal["breakfast", "lunch", "snack", "dinner"]
Ingredient = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Step = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class Meal(BaseModel):
    name: str = Field(max_length=100)
    description: str = Field(max_length=300)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=25)  # each includes a quantity, e.g. "2 eggs"
    steps: list[Step] = Field(default_factory=list, max_length=15)
    kcal: float = Field(ge=30, le=1800)
    protein_g: float = Field(ge=0, le=150)
    carbs_g: float = Field(ge=0, le=300)
    fat_g: float = Field(ge=0, le=150)
    fibre_g: float = Field(ge=0, le=60)
    prep_minutes: int = Field(ge=0, le=180)


class MealResults(BaseModel):
    meals: list[Meal] = Field(min_length=1, max_length=5)


class PlannedMeal(Meal):
    meal_type: MealType


class DailyPlan(BaseModel):
    meals: list[PlannedMeal] = Field(min_length=2, max_length=7)


class CoachReply(BaseModel):
    message: str = Field(max_length=700)


class AiPlanDay(BaseModel):
    meals: list[PlannedMeal] = Field(min_length=2, max_length=4)


class AiPlan(BaseModel):
    """Multi-day plan. Dates are assigned by the backend, in order, starting at start_date."""

    days: list[AiPlanDay] = Field(min_length=1, max_length=7)
    max_output_tokens: ClassVar[int] = 16000  # read by gemini.generate_json
    timeout_s: ClassVar[int] = 60


class GroceryItem(BaseModel):
    name: str = Field(max_length=80)
    quantity: str = Field(max_length=60)


class GroceryGroup(BaseModel):
    name: str = Field(max_length=60)
    items: list[GroceryItem] = Field(min_length=1, max_length=60)


class GroceryList(BaseModel):
    groups: list[GroceryGroup] = Field(min_length=1, max_length=12)
    max_output_tokens: ClassVar[int] = 6000


class PlanMeal(PlannedMeal):
    logged: bool = False

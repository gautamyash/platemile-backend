"""Deterministic calorie and macro targets. No AI involved.

Calorie floors and special-case rules here are placeholders and must be
reviewed by a qualified dietitian before launch.
"""

from dataclasses import dataclass, field
from datetime import date

ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "active": 1.55,
    "very_active": 1.725,
}

CALORIE_FLOOR = {"female": 1200, "male": 1500}
MAX_DEFICIT_FRACTION = 0.25  # never cut more than 25% of TDEE
LOSS_DEFICIT_KCAL = 500
GAIN_SURPLUS_KCAL = 300
MIN_ADULT_AGE = 18
DEFAULT_STEPS_GOAL = 8000
MACRO_ENERGY_TOLERANCE = 0.2  # macro energy (4/4/9) may differ from kcal by at most 20% in a user override


@dataclass(frozen=True)
class Targets:
    bmr: int
    tdee: int
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    water_ml: int
    notes: list[str] = field(default_factory=list)
    fibre_g: int = 25
    steps_goal: int = DEFAULT_STEPS_GOAL


def age_from_birth_year(birth_year: int, today: date | None = None) -> int:
    return (today or date.today()).year - birth_year  # noqa: DTZ011


def bmr_mifflin_st_jeor(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if sex == "male" else base - 161


def calculate_targets(
    *,
    sex: str,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity_level: str,
    goal: str,
) -> Targets:
    if sex not in CALORIE_FLOOR:
        raise ValueError("sex must be 'male' or 'female'")
    if activity_level not in ACTIVITY_FACTORS:
        raise ValueError(f"unknown activity_level: {activity_level}")
    if weight_kg <= 0 or height_cm <= 0 or age <= 0:
        raise ValueError("weight, height and age must be positive")

    notes: list[str] = []
    bmr = bmr_mifflin_st_jeor(sex, weight_kg, height_cm, age)
    tdee = bmr * ACTIVITY_FACTORS[activity_level]
    target = tdee

    if age < MIN_ADULT_AGE:
        notes.append("under_18_no_deficit")
    elif goal == "lose_weight":
        deficit = min(LOSS_DEFICIT_KCAL, tdee * MAX_DEFICIT_FRACTION)
        target = tdee - deficit
    elif goal == "build_muscle":
        target = tdee + GAIN_SURPLUS_KCAL

    floor = CALORIE_FLOOR[sex]
    if age >= MIN_ADULT_AGE and target < floor:
        target = floor
        notes.append("calorie_floor_applied")

    kcal = round(target)

    protein_per_kg = {"build_muscle": 1.8, "lose_weight": 1.6}.get(goal, 1.2)
    protein_g = round(weight_kg * protein_per_kg)
    fat_g = round(kcal * 0.25 / 9)
    carbs_kcal = kcal - protein_g * 4 - fat_g * 9
    carbs_g = max(round(carbs_kcal / 4), 0)

    return Targets(
        bmr=round(bmr),
        tdee=round(tdee),
        kcal=kcal,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        water_ml=round(weight_kg * 35 / 100) * 100,
        notes=notes,
        fibre_g=max(round(kcal / 1000 * 14), 20),  # ~14 g per 1000 kcal, never below 20 g
    )


def calorie_floor(sex: str) -> int:
    return CALORIE_FLOOR[sex]


def check_override(*, sex: str, kcal: int, protein_g: int, carbs_g: int, fat_g: int) -> str | None:
    """Returns a refusal message if user-chosen targets are unsafe, else None."""
    floor = calorie_floor(sex)
    if kcal < floor:
        return f"Daily calories below {floor} kcal are not supported. Please choose {floor} kcal or more."
    energy = protein_g * 4 + carbs_g * 4 + fat_g * 9
    if abs(energy - kcal) > MACRO_ENERGY_TOLERANCE * kcal:
        return "Protein, carbs and fat do not add up to your calorie target. Please adjust them so they roughly match."
    return None

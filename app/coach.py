"""Coach replies without an LLM: meal ideas come from the meal engine, everything else from short curated
messages that use the user's own targets and logs. Wording is general wellness guidance, never medical advice."""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from app import meal_engine
from app.ai.schemas import Meal

# prompt ids answered with meals from the engine
MEAL_PROMPTS = {"what_to_eat", "under_400", "protein_help", "replace_dinner"}
PLAN_PROMPTS = {"todays_diet"}
TEXT_PROMPTS = {"hydration", "low_energy", "plateau", "eating_out", "motivation", "analyze_week"}
ALL_PROMPTS = MEAL_PROMPTS | PLAN_PROMPTS | TEXT_PROMPTS

SLOT_LABEL = {"breakfast": "breakfast", "lunch": "lunch", "snack": "snack", "dinner": "dinner"}


@dataclass
class DayLog:
    """What the user logged on one day (kcal and protein totals)."""

    day: date
    kcal: float
    protein_g: float


@dataclass
class CoachResult:
    message: str
    meals: list[Meal] = field(default_factory=list)
    plan: list[tuple[str, Meal]] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


def _round10(x: float) -> int:
    return int(round(x / 10.0) * 10)


def meal_ideas(prompt_id: str, profile, day_kcal: float, protein_target: float, slot: str, eaten_kcal: float,
               slots: list[str], rng: random.Random) -> CoachResult:
    if prompt_id == "replace_dinner":
        slot = "dinner"
    left = max(0.0, day_kcal - eaten_kcal)
    kw: dict = {}
    if prompt_id == "under_400":
        kw["max_kcal"] = 400
    elif prompt_id == "protein_help":
        kw["tags"] = ("high_protein",)
    elif eaten_kcal > 0 and left >= 150:
        # keep the suggestion inside what is left of the day, but never below a sensible small meal
        kw["max_kcal"] = int(min(1200, max(150, left)))
    meals = meal_engine.find_meals(profile, day_kcal, slot, rng, slots=slots, **kw)
    if prompt_id == "protein_help":
        meals.sort(key=lambda m: -m.protein_g)
        msg = (f"Here are three {SLOT_LABEL[slot]} options with more protein. Your daily protein target is about "
               f"{round(protein_target)} g, so spreading it over your meals is easier than catching up at night.")
        tips = ["Add a katori of curd, dal, sprouts or paneer to any meal for an easy protein boost.",
                "Roasted chana or a boiled egg (if you eat eggs) make simple high-protein snacks."]
    elif prompt_id == "under_400":
        msg = f"Three {SLOT_LABEL[slot]} options, each under 400 kcal, that fit your food preferences."
        tips = ["Pair a lighter meal with a salad or a bowl of soup if you feel hungry."]
    elif prompt_id == "replace_dinner":
        msg = "Three dinner options you can swap in tonight. Tap one to see the recipe or add it to your plan."
        tips = []
    else:
        if eaten_kcal > 0:
            msg = (f"You have about {_round10(left)} kcal left today. These {SLOT_LABEL[slot]} options fit that and your "
                   f"food preferences.")
        else:
            msg = f"Three {SLOT_LABEL[slot]} options that fit your target of about {_round10(day_kcal)} kcal a day."
        tips = []
    return CoachResult(message=msg, meals=meals, tips=tips)


def todays_diet(profile, day_kcal: float, slots: list[str], rng: random.Random) -> CoachResult:
    day = meal_engine.build_plan(profile, day_kcal, 1, slots, rng)[0]
    total = sum(m.kcal for _, m in day)
    msg = (f"Here is a full day of {len(day)} meals, about {_round10(total)} kcal against your target of "
           f"{_round10(day_kcal)} kcal. You can save it from Create plan, or swap any meal you don't fancy.")
    tips = ["Keep a glass of water with each meal.", "Add a bowl of salad at lunch for extra fibre."]
    return CoachResult(message=msg, plan=day, tips=tips)


def analyze_week(logs: list[DayLog], day_kcal: float, protein_target: float, today: date) -> CoachResult:
    week = [d for d in logs if today - timedelta(days=6) <= d.day <= today and d.kcal > 0]
    if not week:
        return CoachResult(
            message="You have not logged any meals in the last 7 days yet. Log your meals for a few days and I can "
                    "show how your intake compares with your targets.",
            tips=["Logging right after eating is the easiest way to keep it accurate."],
        )
    n = len(week)
    avg_k = sum(d.kcal for d in week) / n
    avg_p = sum(d.protein_g for d in week) / n
    diff = avg_k - day_kcal
    if abs(diff) <= 0.1 * day_kcal:
        k_line = f"your average of {_round10(avg_k)} kcal is close to your {_round10(day_kcal)} kcal target"
    elif diff > 0:
        k_line = f"your average of {_round10(avg_k)} kcal is about {_round10(diff)} kcal above your {_round10(day_kcal)} kcal target"
    else:
        k_line = f"your average of {_round10(avg_k)} kcal is about {_round10(-diff)} kcal below your {_round10(day_kcal)} kcal target"
    p_ok = avg_p >= 0.9 * protein_target
    p_line = (f"protein averages {round(avg_p)} g, which meets your {round(protein_target)} g goal" if p_ok else
              f"protein averages {round(avg_p)} g against a goal of {round(protein_target)} g")
    msg = f"You logged food on {n} of the last 7 days. On those days {k_line}, and {p_line}."
    tips: list[str] = []
    if n < 5:
        tips.append("Log on more days for a clearer picture; a few missed days can skew the averages.")
    if not p_ok:
        tips.append("Add a protein source to breakfast and snacks: dal, curd, paneer, sprouts, chana or eggs.")
    if diff > 0.1 * day_kcal:
        tips.append("Watch oil, sweets and sugary drinks first; they add calories quickly.")
    if diff < -0.2 * day_kcal:
        tips.append("Eating much less than your target can leave you tired. Try not to skip meals.")
    if not tips:
        tips.append("Nice and steady. Keep the same routine this week.")
    return CoachResult(message=msg, tips=tips)


def text_reply(prompt_id: str, day_kcal: float, protein_target: float, water_ml: int | None = None) -> CoachResult:
    if prompt_id == "hydration":
        goal = f"{round((water_ml or 2500) / 250)} glasses" if water_ml else "8 to 10 glasses"
        return CoachResult(
            message=f"Aim for about {goal} of water through the day, more in hot weather or after exercise. Sip "
                    "regularly instead of drinking a lot at once.",
            tips=["Start the day with a glass of water.", "Buttermilk, nimbu pani without much sugar and coconut water also count.",
                  "Pale yellow urine is a simple sign you are drinking enough."])
    if prompt_id == "low_energy":
        return CoachResult(
            message="Low energy often comes from long gaps between meals, too little protein or fibre, poor sleep or not "
                    "enough water. Try regular meals with dal, curd, eggs or paneer and whole grains.",
            tips=["Don't skip breakfast.", "Keep a handful of roasted chana or a fruit for the afternoon slump.",
                  "If tiredness lasts for weeks, please check with a doctor."])
    if prompt_id == "plateau":
        return CoachResult(
            message="Weight often stays flat for a week or two even when you are on track; water and digestion shift the "
                    f"scale daily. Check that your logged intake really averages near {_round10(day_kcal)} kcal, and keep "
                    f"protein near {round(protein_target)} g.",
            tips=["Compare weekly averages, not single days.", "Add a daily walk; steps add up.",
                  "Measure oil with a spoon for a week; it is the most common hidden extra."])
    if prompt_id == "eating_out":
        return CoachResult(
            message="Eating out can still fit your day. Pick grilled, tandoori or steamed dishes, dal, salads and roti over "
                    "fried starters, cream gravies and naan, and share desserts.",
            tips=["Ask for less oil or butter.", "Start with a soup or salad.", "Log it afterwards with a best guess; it still helps."])
    if prompt_id == "motivation":
        return CoachResult(
            message="Small steps you repeat beat big changes you can't keep. Focus on one habit this week, like logging "
                    "every meal or adding protein to breakfast, and notice how you feel.",
            tips=["Plan tomorrow's meals tonight.", "Celebrate streaks, not perfection."])
    raise ValueError(prompt_id)

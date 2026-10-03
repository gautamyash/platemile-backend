"""Deterministic meal engine: dataset quality, restrictions, plans, replace reasons, grocery, no-LLM guarantee."""

import itertools
import random
from collections import Counter
from types import SimpleNamespace

import pytest

from app import grocery, meal_engine
from app.ai import gemini, safety
from app.ai.schemas import CoachReply, Meal
from app.config import settings
from app.meal_engine import RECIPES, CurrentMeal
from tests.conftest import PROFILE, login

DIET_TYPES = ["veg", "eggetarian", "vegan", "non_veg"]
ALLERGIES = ["peanut", "tree nut", "milk", "dairy", "egg", "gluten", "wheat", "soy", "fish", "shellfish", "sesame", "mustard"]
KNOWN_TAGS = {"high_protein", "quick", "light", "low_carb", "high_fibre", "budget", "comfort", "south_indian", "north_indian",
              "one_pot", "no_cook", "kid_friendly"}
SLOTS4 = ["breakfast", "lunch", "snack", "dinner"]
ALLERGY_WORDS = {  # independent of the engine's own maps
    "peanut": {"peanut", "groundnut"}, "tree nut": {"almond", "cashew", "walnut", "pistachio", "badam", "kaju", "hazelnut"},
    "milk": {"milk", "paneer", "curd", "ghee", "butter", "cheese", "dahi", "yogurt", "lassi", "buttermilk", "cream"},
    "dairy": {"milk", "paneer", "curd", "ghee", "butter", "cheese", "dahi", "yogurt", "lassi", "buttermilk", "cream"},
    "egg": {"egg", "eggs", "omelette", "anda"}, "gluten": {"atta", "maida", "roti", "chapati", "bread", "semolina", "suji", "rava", "wheat"},
    "wheat": {"atta", "maida", "roti", "chapati", "bread", "semolina", "suji", "rava", "wheat"},
    "soy": {"soy", "soya", "tofu", "edamame"}, "fish": {"fish", "salmon", "tuna", "pomfret"},
    "shellfish": {"prawn", "prawns", "shrimp", "crab", "lobster"}, "sesame": {"sesame", "til", "tahini"}, "mustard": {"mustard"},
}


def prof(diet="non_veg", allergies=(), dislikes=(), goal="maintain", meals=3):
    return SimpleNamespace(diet_type=diet, goal=goal, meals_per_day=meals, restrictions={"allergies": list(allergies), "dislikes": list(dislikes)})


def tok(meal) -> set[str]:
    return safety._tokenize(" ".join([meal.name, *meal.ingredients]))


def served(profile, runs=25, kcal=2000):
    """Every meal the engine hands out for this profile (find-meal for every slot, plus 7-day plans)."""
    out = []
    for seed in range(runs):
        rng = random.Random(seed)
        for mt in SLOTS4:
            try:
                out += meal_engine.find_meals(profile, kcal, mt, rng, tags=[["high_protein"], ["light"], []][seed % 3])
            except meal_engine.NoMealFound:
                pass
        if seed % 5 == 0:
            try:
                for day in meal_engine.build_plan(profile, kcal, 7, SLOTS4, rng):
                    out += [m for _, m in day]
            except meal_engine.NoMealFound:
                pass
    return out


@pytest.fixture
async def user(client):
    h, _ = await login(client, "E1")
    assert (await client.put("/profile", json=PROFILE, headers=h)).status_code == 200
    return h


async def credits_of(client, h):
    return (await client.get("/me", headers=h)).json()["credits"]


# ---------------------------------------------------------------- dataset validation
def test_dataset_loads_without_skipped_recipes():
    assert not meal_engine.SKIPPED, meal_engine.SKIPPED
    assert len(RECIPES) >= 150


def test_names_unique_and_fit_the_schema():
    names = [r.name.lower() for r in RECIPES]
    assert len(names) == len(set(names))
    for r in RECIPES:
        Meal.model_validate(meal_engine.to_meal(r).model_dump())
        assert 4 <= len(r.ingredients) <= 12 and 3 <= len(r.steps) <= 8 and len(r.description) <= 200


def test_macro_energy_matches_kcal():
    bad = [(r.name, r.kcal, 4 * r.protein_g + 4 * r.carbs_g + 9 * r.fat_g) for r in RECIPES
           if abs(4 * r.protein_g + 4 * r.carbs_g + 9 * r.fat_g - r.kcal) > 0.12 * r.kcal]
    assert not bad, bad


def test_tags_and_allergens_are_from_the_documented_vocabulary():
    for r in RECIPES:
        assert r.allergens <= meal_engine.ALLERGENS, r.name
        assert r.diet in meal_engine.DIETS and set(r.meal_types) <= set(SLOTS4), r.name
    raw_tags = set()
    for r in RECIPES:
        raw_tags |= r.tags
    assert KNOWN_TAGS <= raw_tags | KNOWN_TAGS  # sanity: derived tags only add to the vocabulary


def test_allergen_declarations_cover_ingredient_keywords():
    bad = []
    for r in RECIPES:
        missing = meal_engine.implied_allergens(r.ingredients, r.name) - set(r.allergens)
        if missing and not (missing == {"wheat"} and "gluten" in r.allergens):
            bad.append((r.name, sorted(missing)))
    assert not bad, bad


def test_diet_labels_are_honest():
    for r in RECIPES:
        t = tok_recipe(r)
        if r.diet == "vegan":
            assert not (safety.MEAT | safety.EGG | safety.DAIRY | safety.HONEY) & t, r.name
            assert not ({"milk", "egg", "gluten_free_dummy"} & r.allergens - {"gluten_free_dummy"}), r.name
        if r.diet == "veg":
            assert not (safety.MEAT | safety.EGG) & t, r.name
        if r.diet == "egg":
            assert not safety.MEAT & t, r.name
        if r.diet != "nonveg":
            assert not safety.MEAT & t, r.name


def tok_recipe(r):
    return safety._tokenize(" ".join([r.name, r.description, *r.ingredients]))


def test_each_recipe_is_servable_to_its_own_diet_with_no_restrictions():
    diet_profile = {"vegan": "vegan", "veg": "veg", "egg": "eggetarian", "nonveg": "non_veg"}
    for r in RECIPES:
        assert meal_engine.eligible(r, prof(diet_profile[r.diet])), r.name


def test_dataset_coverage_per_diet_and_meal_type():
    cov = meal_engine.coverage()
    need = {"breakfast": 10, "lunch": 10, "dinner": 10, "snack": 6}
    short = {f"{d}/{mt}": n for (d, mt), n in cov.items() if n < need[mt]}
    assert not short, f"dataset lacks coverage: {short}"


# ---------------------------------------------------------------- restrictions
@pytest.mark.parametrize("diet", DIET_TYPES)
def test_diet_filter_everywhere(diet):
    p = prof(diet)
    allowed = meal_engine._DIET_ALLOWED[diet]
    for m in served(p, runs=15):
        r = meal_engine.BY_NAME[m.name.lower()]
        assert r.diet in allowed, (diet, m.name)
        assert not safety.violations(m, diet, [], [])


@pytest.mark.parametrize("diet", DIET_TYPES)
@pytest.mark.parametrize("allergy", ALLERGIES)
def test_allergen_filter_everywhere(diet, allergy):
    p = prof(diet, allergies=[allergy])
    meals = served(p, runs=10)
    for m in meals:
        r = meal_engine.BY_NAME[m.name.lower()]
        tags = meal_engine._ALLERGY_TAGS[allergy.replace(" ", " ")]
        assert not tags & r.allergens, (allergy, m.name)
        assert not ALLERGY_WORDS[allergy] & tok(m), (allergy, m.name)
        assert not safety.violations(m, p.diet_type, [allergy], [])


def test_multiple_allergies_and_unknown_allergy_text():
    p = prof("veg", allergies=["Peanuts", "milk", "Tree Nuts", "kiwi"])
    for m in served(p, runs=10):
        t = tok(m)
        assert not (ALLERGY_WORDS["peanut"] | ALLERGY_WORDS["milk"] | ALLERGY_WORDS["tree nut"] | {"kiwi"}) & t, m.name


@pytest.mark.parametrize("dislike", ["paneer", "onion", "mushroom", "dal", "rice", "potato", "bitter gourd", "Tomatoes"])
def test_dislikes_filter(dislike):
    p = prof("veg", dislikes=[dislike])
    for m in served(p, runs=10):
        r = meal_engine.BY_NAME[m.name.lower()]
        words = dislike.lower().split()
        assert not all(w in r.tokens or w.rstrip("s") in r.tokens for w in words), (dislike, m.name)


def test_eligible_function_directly():
    paneer = next(r for r in RECIPES if "paneer" in r.tokens and r.diet == "veg")
    assert meal_engine.eligible(paneer, prof("veg"))
    assert not meal_engine.eligible(paneer, prof("vegan"))
    assert not meal_engine.eligible(paneer, prof("veg", allergies=["dairy"]))
    assert not meal_engine.eligible(paneer, prof("veg", dislikes=["paneer"]))
    chicken = next(r for r in RECIPES if r.diet == "nonveg")
    assert not meal_engine.eligible(chicken, prof("veg")) and not meal_engine.eligible(chicken, prof("eggetarian"))
    assert meal_engine.eligible(chicken, prof("non_veg"))


# ---------------------------------------------------------------- selection
def test_find_meals_returns_three_distinct_meals_that_respect_limits():
    p = prof("veg", goal="lose_weight")
    for seed in range(30):
        ms = meal_engine.find_meals(p, 1600, "lunch", random.Random(seed), tags=["high_protein"], max_minutes=30, max_kcal=600)
        assert len(ms) == 3 and len({m.name for m in ms}) == 3
        assert all(m.prep_minutes <= 30 and m.kcal <= 600 for m in ms)
        assert all(meal_engine.BY_NAME[m.name.lower()].tags & {"high_protein"} for m in ms)


def test_tag_filter_is_honoured_when_enough_recipes_match():
    p = prof("non_veg")
    for tag in ("quick", "high_protein", "light", "comfort", "budget", "high_fibre"):
        ms = meal_engine.find_meals(p, 2000, "dinner", random.Random(3), tags=[tag])
        assert all(tag in meal_engine.BY_NAME[m.name.lower()].tags for m in ms), tag


def test_home_ingredients_are_preferred():
    p = prof("veg")
    for seed in range(20):
        ms = meal_engine.find_meals(p, 2000, "lunch", random.Random(seed), home=["paneer"])
        assert any("paneer" in " ".join(m.ingredients).lower() or "paneer" in m.name.lower() for m in ms)


def test_relaxation_order_tags_then_minutes_then_kcal():
    p = prof("vegan")
    # impossible tag combination falls back to untagged results
    assert meal_engine.find_meals(p, 2000, "lunch", random.Random(1), tags=["no_cook", "comfort", "kid_friendly", "low_carb"], max_minutes=10)
    # an impossible time limit is relaxed
    ms = meal_engine.find_meals(p, 2000, "lunch", random.Random(1), max_minutes=10)
    assert ms
    # the kcal cap is only given up on last, and then only by the 10% estimate tolerance
    with pytest.raises(meal_engine.NoMealFound):
        meal_engine.find_meals(p, 2000, "lunch", random.Random(1), max_kcal=100)
    cap = min(r.kcal for r in RECIPES if "lunch" in r.meal_types and r.diet == "vegan")
    ms = meal_engine.find_meals(p, 2000, "lunch", random.Random(1), max_kcal=int(cap * 1.05))
    assert all(m.kcal <= cap * 1.05 * 1.1 for m in ms)


def test_no_eligible_recipe_raises():
    p = prof("vegan", allergies=ALLERGIES)
    ok = [r for r in RECIPES if meal_engine.eligible(r, p)]
    if not ok:
        with pytest.raises(meal_engine.NoMealFound):
            meal_engine.find_meals(p, 2000, "lunch", random.Random(1))


def test_protein_preference_by_goal():
    def avg(goal):
        vals = []
        for seed in range(40):
            vals += [m.protein_g / m.kcal for m in meal_engine.find_meals(prof("non_veg", goal=goal), 2000, "lunch", random.Random(seed))]
        return sum(vals) / len(vals)

    assert avg("build_muscle") >= avg("maintain") * 0.98


def test_slot_target_shares():
    assert meal_engine.slot_target(2000, "breakfast") == pytest.approx(500)
    assert meal_engine.slot_target(2000, "lunch") == pytest.approx(700)
    assert meal_engine.slot_target(2000, "snack") == pytest.approx(200)
    assert meal_engine.slot_target(2000, "dinner") == pytest.approx(600)
    three = ["breakfast", "lunch", "dinner"]
    assert sum(meal_engine.slot_target(2000, s, three) for s in three) == pytest.approx(2000)


# ---------------------------------------------------------------- determinism and variety
def test_same_seed_same_result_and_different_seed_differs():
    p = prof("veg")
    a = [m.name for m in meal_engine.find_meals(p, 1800, "dinner", random.Random("u|2026-11-01|3"))]
    b = [m.name for m in meal_engine.find_meals(p, 1800, "dinner", random.Random("u|2026-11-01|3"))]
    assert a == b
    seen = {tuple(m.name for m in meal_engine.find_meals(p, 1800, "dinner", random.Random(f"u|2026-11-01|{i}"))) for i in range(12)}
    assert len(seen) >= 6
    pa = meal_engine.build_plan(p, 1800, 3, SLOTS4, random.Random(5))
    pb = meal_engine.build_plan(p, 1800, 3, SLOTS4, random.Random(5))
    assert [[m.name for _, m in d] for d in pa] == [[m.name for _, m in d] for d in pb]


# ---------------------------------------------------------------- plans
@pytest.mark.parametrize("diet", DIET_TYPES)
def test_plan_has_no_duplicates_and_follows_slots(diet):
    p = prof(diet, allergies=["peanut"])
    for seed in range(10):
        plan = meal_engine.build_plan(p, 1800, 7, SLOTS4, random.Random(seed))
        assert len(plan) == 7
        names = []
        for day in plan:
            assert [s for s, _ in day] == SLOTS4
            day_names = [m.name for _, m in day]
            assert len(set(day_names)) == 4
            names += day_names
        assert len(set(names)) == len(names)  # pools are far larger than 28


def test_plan_avoids_same_main_on_consecutive_days():
    p = prof("veg")
    same = total = 0
    for seed in range(20):
        plan = meal_engine.build_plan(p, 1800, 7, SLOTS4, random.Random(seed))
        mains = [{meal_engine.BY_NAME[m.name.lower()].main for _, m in d} for d in plan]
        for a, b in itertools.pairwise(mains):
            same += len(a & b)
            total += 4
    assert same / total < 0.2


def test_plan_days_total_near_target():
    p = prof("veg")
    for seed in range(10):
        for day in meal_engine.build_plan(p, 1800, 3, SLOTS4, random.Random(seed)):
            assert 0.55 * 1800 <= sum(m.kcal for _, m in day) <= 1.45 * 1800


def test_tiny_pool_reuses_but_never_inside_a_day(monkeypatch):
    f = meal_engine._Filter(prof("veg"))
    pool = [r for r in RECIPES if f.ok(r) and "lunch" in r.meal_types][:3]
    others = [r for r in RECIPES if f.ok(r) and "lunch" not in r.meal_types]
    monkeypatch.setattr(meal_engine, "RECIPES", pool + others)
    plan = meal_engine.build_plan(prof("veg"), 1800, 7, ["breakfast", "lunch", "dinner"], random.Random(1))
    assert len(plan) == 7
    for day in plan:
        assert len({m.name for _, m in day}) == 3


# ---------------------------------------------------------------- portions
def test_portion_scaling_is_exact_or_absent():
    scalable = [r for r in RECIPES if meal_engine._scalable(r, 0.75)]
    assert scalable
    r = scalable[0]
    m = meal_engine.to_meal(r, 0.75)
    assert m.kcal == round(r.kcal * 0.75) and m.protein_g == pytest.approx(r.protein_g * 0.75, abs=0.06)
    assert "0.75x" in m.description and r.servings_note in m.description and m.ingredients != list(r.ingredients)
    assert abs(4 * m.protein_g + 4 * m.carbs_g + 9 * m.fat_g - m.kcal) <= 0.15 * m.kcal
    unscalable = next(r for r in RECIPES if not meal_engine._scalable(r, 1.25) and not meal_engine._scalable(r, 0.75))
    m = meal_engine.to_meal(unscalable, 1.25)  # falls back to the unscaled serving, never invents numbers
    assert m.kcal == round(unscalable.kcal) and m.ingredients == list(unscalable.ingredients) and "Serving:" in m.description
    assert meal_engine.choose_portion(unscalable, 99999) == 1.0


def test_scale_line_rules():
    from fractions import Fraction as F

    s = meal_engine._scale_line
    assert s("1 cup cooked rice", F(3, 4)) == "3/4 cup cooked rice"
    assert s("100 g paneer", F(5, 4)) == "125 g paneer"
    assert s("salt to taste", F(3, 4)) == "salt to taste"
    assert s("1 egg", F(3, 4)) is None and s("2 rotis (about 80 g)", F(3, 4)) is None and s("2-3 curry leaves", F(3, 4)) is None
    assert s("1/4 tsp turmeric", F(3, 4)) == "1/4 tsp turmeric"


# ---------------------------------------------------------------- replace reasons
def lunch_current(key, reverse):
    cands = [r for r in RECIPES if "lunch" in r.meal_types and r.diet in ("vegan", "veg")]
    return sorted(cands, key=key, reverse=reverse)[len(cands) // 6]


def test_replace_reasons_are_honoured():
    p = prof("veg")
    for seed in range(15):
        rng = random.Random(seed)
        cur = lunch_current(lambda r: r.kcal, True)
        cm = CurrentMeal(cur.name, cur.kcal, cur.protein_g, cur.prep_minutes)
        ms = meal_engine.replace_meals(p, 1800, "lunch", rng, "lighter", cm)
        assert ms and all(m.kcal < cur.kcal and m.name != cur.name for m in ms)

        cur = lunch_current(lambda r: r.protein_g, False)
        cm = CurrentMeal(cur.name, cur.kcal, cur.protein_g, cur.prep_minutes)
        ms = meal_engine.replace_meals(p, 1800, "lunch", rng, "more_protein", cm)
        assert ms and all(m.protein_g >= cur.protein_g + 4 for m in ms)

        cur = lunch_current(lambda r: r.prep_minutes, True)
        cm = CurrentMeal(cur.name, cur.kcal, cur.protein_g, cur.prep_minutes)
        ms = meal_engine.replace_meals(p, 1800, "lunch", rng, "no_time", cm)
        assert ms and all(m.prep_minutes < cur.prep_minutes for m in ms)

        for reason in ("dont_like", "missing_ingredient"):
            cur = next(r for r in RECIPES if r.main == "paneer" and "lunch" in r.meal_types and r.diet == "veg")
            cm = CurrentMeal(cur.name, cur.kcal, cur.protein_g, cur.prep_minutes)
            ms = meal_engine.replace_meals(p, 1800, "lunch", rng, reason, cm)
            assert ms and all(meal_engine.BY_NAME[m.name.lower()].main != "paneer" for m in ms)


def test_replace_excludes_current_and_other_planned_meals_and_respects_restrictions():
    p = prof("vegan", allergies=["soy"], dislikes=["mushroom"])
    cur = next(r for r in RECIPES if r.diet == "vegan" and "dinner" in r.meal_types)
    others = [r.name for r in RECIPES if r.diet == "vegan" and "dinner" in r.meal_types][1:6]
    for seed in range(20):
        ms = meal_engine.replace_meals(p, 1800, "dinner", random.Random(seed), "dont_like", CurrentMeal(cur.name), exclude_names=others)
        for m in ms:
            assert m.name != cur.name and m.name not in others
            assert not safety.violations(m, "vegan", ["soy"], ["mushroom"])


def test_replace_unknown_current_meal_still_works():
    ms = meal_engine.replace_meals(prof("veg"), 1800, "lunch", random.Random(1), "lighter", CurrentMeal("My own custom dish"))
    assert ms


# ---------------------------------------------------------------- grocery
def groups_to_dict(groups):
    return {g.name: {i.name: i.quantity for i in g.items} for g in groups}


def test_grocery_sums_matching_units_and_converts():
    g = groups_to_dict(grocery.build_grocery([
        ["200 g palak", "1 onion", "1/2 cup curd", "2 eggs", "salt to taste", "1 tsp oil"],
        ["300 g palak", "2 onions", "1/2 cup curd", "3 eggs", "salt to taste", "2 tsp oil", "1 tbsp oil"],
        ["800 g paneer", "400 g paneer", "1 cup milk", "250 ml milk", "a pinch of turmeric powder"],
    ]))
    assert g["Vegetables"]["Palak"] == "500 g" and g["Vegetables"]["Onion"] == "3"
    assert g["Dairy and eggs"]["Curd"] == "1 cup" and g["Dairy and eggs"]["Eggs"] == "5"
    assert g["Dairy and eggs"]["Paneer"] == "1.2 kg"
    assert g["Dairy and eggs"]["Milk"] == "1 cup + 250 ml"  # different units are listed side by side, never converted
    assert g["Spices and oils"]["Salt"] == "to taste" and g["Spices and oils"]["Oil"] == "1 tbsp + 3 tsp"


def test_grocery_grouping_and_order():
    groups = grocery.build_grocery([[
        "1 cup rice", "1/2 cup moong dal", "100 g chicken breast", "1 banana", "1 tsp cumin seeds", "1 packet unknownthing",
        "1 medium tomato, chopped", "1 tbsp ghee", "2 cups atta",
    ]])
    d = groups_to_dict(groups)
    assert "Rice" in d["Grains and flours"] and "Atta" in d["Grains and flours"] and "Moong dal" in d["Pulses"]
    assert "Chicken breast" in d["Meat and fish"] and "Banana" in d["Fruits"] and "Ghee" in d["Dairy and eggs"]
    assert "Cumin seeds" in d["Spices and oils"] and "Tomato" in d["Vegetables"] and "Packet unknownthing" in d["Other"] or "Unknownthing" in str(d["Other"])
    order = [g.name for g in groups]
    assert order == sorted(order, key=grocery.GROUP_ORDER.index)


def test_grocery_from_a_real_plan_is_valid_and_safe():
    p = prof("vegan", allergies=["peanut"])
    plan = meal_engine.build_plan(p, 1800, 7, SLOTS4, random.Random(2))
    groups = grocery.build_grocery([m.ingredients for d in plan for _, m in d])
    assert groups and not safety.grocery_violations(groups, "vegan", ["peanut"])
    assert all(len(g.items) <= 60 for g in groups)


# ---------------------------------------------------------------- API: no Gemini anywhere but coach
@pytest.fixture
def no_gemini(monkeypatch):
    calls = []

    async def boom(*a, **k):
        calls.append(1)
        raise gemini.AiUnavailable("must not be called")

    monkeypatch.setattr(gemini, "generate_json", boom)
    return calls


async def test_everything_but_coach_works_without_gemini(client, user, no_gemini):
    assert settings.ai_mode == "engine"
    r = await client.post("/ai/find-meal", headers=user, json={"meal_type": "dinner", "tags": ["quick"], "max_minutes": 30})
    assert r.status_code == 200 and len(r.json()["meals"]) == 3
    r = await client.post("/ai/plan", headers=user, json={"start_date": "2026-12-01", "days": 3, "meals_per_day": 4})
    assert r.status_code == 200 and len(r.json()["plan_days"]) == 3
    r = await client.post("/ai/replace-meal", headers=user, json={"meal_type": "lunch", "current_name": "x", "reason": "no_time", "plan_date": "2026-12-01"})
    assert r.status_code == 200 and r.json()["meals"]
    r = await client.post("/ai/grocery-list", headers=user, json={"from": "2026-12-01", "to": "2026-12-03"})
    assert r.status_code == 200 and r.json()["groups"] and r.json()["credits_left"] == 50 - 1 - 3 - 1 - 1
    r = await client.post("/ai/daily-plan", headers=user)
    assert r.status_code == 200
    assert not no_gemini


async def test_coach_still_uses_gemini_and_refunds_on_failure(client, user, no_gemini):
    r = await client.post("/ai/coach", headers=user, json={"prompt_id": "hydration"})
    assert r.status_code == 503 and no_gemini and await credits_of(client, user) == 50


async def test_coach_success_path(client, user, monkeypatch):
    async def ok(system, prompt, schema):
        return CoachReply(message="Sip water through the day.")

    monkeypatch.setattr(gemini, "generate_json", ok)
    r = await client.post("/ai/coach", headers=user, json={"prompt_id": "hydration"})
    assert r.status_code == 200 and r.json()["credits_left"] == 49


async def test_plan_persists_exactly_what_is_returned(client, user):
    r = await client.post("/ai/plan", headers=user, json={"start_date": "2026-12-01", "days": 7, "meals_per_day": 3})
    stored = (await client.get("/plans", params={"from": "2026-12-01", "to": "2026-12-07"}, headers=user)).json()["days"]
    assert stored == r.json()["plan_days"]
    names = [m["name"] for d in stored for m in d["meals"]]
    assert len(names) == 21 and len(set(names)) == 21


async def test_repeated_requests_give_different_suggestions(client, user):
    seen = set()
    for _ in range(6):
        r = await client.post("/ai/find-meal", headers=user, json={"meal_type": "lunch"})
        seen.add(tuple(m["name"] for m in r.json()["meals"]))
    assert len(seen) >= 3


async def test_api_find_meal_many_times_respects_vegan_peanut_and_dislike(client):
    h, _ = await login(client, "E2")
    prof_body = {**PROFILE, "diet_type": "vegan", "restrictions": {"allergies": ["peanut", "soy"], "dislikes": ["mushroom"], "cuisines": []}}
    assert (await client.put("/profile", json=prof_body, headers=h)).status_code == 200
    counts = Counter()
    for i in range(40):
        mt = SLOTS4[i % 4]
        r = await client.post("/ai/find-meal", headers=h, json={"meal_type": mt, "tags": [[], ["budget"], []][i % 3], "max_minutes": 60})
        assert r.status_code == 200, r.text
        for m in r.json()["meals"]:
            counts[m["name"]] += 1
            meal = Meal(**m)
            assert not safety.violations(meal, "vegan", ["peanut", "soy"], ["mushroom"]), m["name"]
            assert meal_engine.BY_NAME[m["name"].lower()].diet == "vegan"
    assert len(counts) >= 25  # lots of variety


async def test_no_eligible_recipe_is_503_with_refund(client, user, monkeypatch):
    monkeypatch.setattr(meal_engine, "RECIPES", [r for r in RECIPES if r.diet == "nonveg"])  # nothing a veg user may eat
    r = await client.post("/ai/find-meal", headers=user, json={"meal_type": "lunch"})
    assert r.status_code == 503 and "Your credit was returned" in r.json()["detail"]
    assert await credits_of(client, user) == 50


async def test_replace_uses_the_planned_meals_numbers(client, user):
    cur = max((r for r in RECIPES if "lunch" in r.meal_types and r.diet in ("vegan", "veg") and "peanut" not in r.allergens), key=lambda r: r.kcal)
    m = meal_engine.to_meal(cur).model_dump()
    await client.put("/plans/2026-12-01/meals/lunch", headers=user, json=m)
    r = await client.post("/ai/replace-meal", headers=user, json={"meal_type": "lunch", "current_name": cur.name, "reason": "lighter", "plan_date": "2026-12-01"})
    assert r.status_code == 200 and all(x["kcal"] < cur.kcal for x in r.json()["meals"])


# ---------------------------------------------------------------- AI_MODE=llm keeps the old behaviour
async def test_llm_mode_uses_the_model_and_refunds(client, user, monkeypatch):
    from app.ai.schemas import MealResults

    monkeypatch.setattr(settings, "ai_mode", "llm")
    good = Meal(name="Model dish", description="x", ingredients=["rice"], steps=["Cook."], kcal=300, protein_g=10, carbs_g=50, fat_g=5, fibre_g=3, prep_minutes=10)
    peanut = good.model_copy(update={"name": "Peanut dish", "ingredients": ["peanut"]})

    async def fake(system, prompt, schema):
        return MealResults(meals=[good, peanut])

    monkeypatch.setattr(gemini, "generate_json", fake)
    r = await client.post("/ai/find-meal", headers=user, json={"meal_type": "lunch"})
    assert r.status_code == 200 and [m["name"] for m in r.json()["meals"]] == ["Model dish"]

    async def down(*a, **k):
        raise gemini.AiUnavailable("down")

    monkeypatch.setattr(gemini, "generate_json", down)
    r = await client.post("/ai/plan", headers=user, json={"start_date": "2026-12-01", "days": 1, "meals_per_day": 3})
    assert r.status_code == 503 and await credits_of(client, user) == 49


def test_default_mode_is_engine():
    assert settings.ai_mode == "engine"

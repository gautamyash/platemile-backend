"""Guards around AI output. The model is never trusted: every result is checked against the user's
diet type, allergies and sane nutrition ranges before it reaches the app."""

from app.ai.schemas import Meal

# Keyword lists are intentionally simple and conservative. They need expansion (Hindi/regional names) before launch.
MEAT = {"chicken", "mutton", "lamb", "beef", "pork", "fish", "prawn", "shrimp", "crab", "keema", "bacon", "ham",
        "turkey", "salmon", "tuna", "sausage", "meat", "gosht", "murgh"}
EGG = {"egg", "eggs", "omelette", "omelet", "anda"}
DAIRY = {"milk", "paneer", "curd", "yogurt", "yoghurt", "dahi", "ghee", "butter", "cheese", "cream", "khoya",
         "lassi", "buttermilk", "chaas", "whey"}
HONEY = {"honey"}

ALLERGEN_ALIASES = {
    "peanut": {"peanut", "groundnut", "moongphali"},
    "tree nut": {"almond", "cashew", "walnut", "pistachio", "hazelnut", "pecan", "badam", "kaju"},
    "milk": DAIRY,
    "dairy": DAIRY,
    "egg": EGG,
    "gluten": {"wheat", "atta", "maida", "roti", "chapati", "bread", "barley", "rye", "semolina", "suji", "rava"},
    "soy": {"soy", "soya", "tofu", "edamame"},
    "fish": {"fish", "salmon", "tuna", "pomfret"},
    "shellfish": {"prawn", "shrimp", "crab", "lobster"},
    "sesame": {"sesame", "til", "tahini"},
}

FORBIDDEN_CLAIMS = ("cure", "cures", "treats disease", "detox", "guaranteed", "lose weight fast", "burn fat")


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    for ch in ",.()/-":
        text = text.replace(ch, " ")
    words = set(text.split())
    return words | {w[:-1] for w in words if len(w) > 3 and w.endswith("s")}  # so "peanuts" also matches "peanut"


def _tokens(meal: Meal) -> set[str]:
    return _tokenize(" ".join([meal.name, meal.description, *meal.ingredients]))


def forbidden_for_diet(diet_type: str) -> set[str]:
    if diet_type == "veg":
        return MEAT | EGG
    if diet_type == "eggetarian":
        return MEAT
    if diet_type == "vegan":
        return MEAT | EGG | DAIRY | HONEY
    return set()


def violations(meal: Meal, diet_type: str, allergies: list[str], dislikes: list[str]) -> list[str]:
    toks = _tokens(meal)
    found: list[str] = []
    bad = forbidden_for_diet(diet_type) & toks
    if bad:
        found.append(f"diet:{min(bad)}")
    for a in allergies:
        key = a.strip().lower()
        words = ALLERGEN_ALIASES.get(key, {key})
        hit = words & toks
        if hit:
            found.append(f"allergen:{min(hit)}")
    for d in dislikes:
        if d.strip().lower() and d.strip().lower() in toks:
            found.append(f"dislike:{d.strip().lower()}")
    blob = f"{meal.name} {meal.description}".lower()
    if any(c in blob for c in FORBIDDEN_CLAIMS):
        found.append("claim")
    # macro energy must roughly match the stated kcal (4/4/9), allow generous tolerance
    energy = meal.protein_g * 4 + meal.carbs_g * 4 + meal.fat_g * 9
    if meal.kcal > 0 and not (0.6 * meal.kcal <= energy <= 1.4 * meal.kcal):
        found.append("macro_mismatch")
    return found


def filter_meals(meals: list[Meal], diet_type: str, allergies: list[str], dislikes: list[str]) -> list[Meal]:
    return [m for m in meals if not violations(m, diet_type, allergies, dislikes)]


def grocery_violations(groups, diet_type: str, allergies: list[str]) -> list[str]:
    """Checks grocery items (diet and allergens only; the list is built from already-planned meals)."""
    found: list[str] = []
    diet_bad = forbidden_for_diet(diet_type)
    for g in groups:
        for item in g.items:
            toks = _tokenize(item.name)
            if diet_bad & toks:
                found.append(f"diet:{min(diet_bad & toks)}")
            for a in allergies:
                key = a.strip().lower()
                hit = ALLERGEN_ALIASES.get(key, {key}) & toks
                if hit:
                    found.append(f"allergen:{min(hit)}")
    return found

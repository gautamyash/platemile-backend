"""Deterministic meal engine: picks meals from the curated dataset in app/meal_data. No LLM involved.

Everything here is pure (no I/O besides importing the dataset). Callers pass a `random.Random` so results are
reproducible for a given seed but vary between requests. All nutrition values come from the dataset (estimates);
the only arithmetic is a 0.75x / 1x / 1.25x serving factor, and ingredient quantities are scaled only when that
can be done exactly.
"""

import importlib
import logging
import pkgutil
import random
import re
from dataclasses import dataclass
from fractions import Fraction

from app import meal_data
from app.ai import safety
from app.ai.schemas import Meal, PlannedMeal

log = logging.getLogger("meal_engine")

MEAL_TYPES = ("breakfast", "lunch", "snack", "dinner")
DIETS = ("vegan", "veg", "egg", "nonveg")
ALLERGENS = {"peanut", "tree_nut", "milk", "egg", "wheat", "gluten", "soy", "fish", "shellfish", "sesame", "mustard"}
SHARES = {"breakfast": 0.25, "lunch": 0.35, "snack": 0.10, "dinner": 0.30}
PORTIONS = (0.75, 1.0, 1.25)
JITTER = 3.0  # seeded random spread added to scores: how much variety there is between requests
MACRO_TOLERANCE = 0.12

# user profile diet_type -> recipe diets that are allowed
_DIET_ALLOWED = {
    "vegan": {"vegan"},
    "veg": {"vegan", "veg"},
    "eggetarian": {"vegan", "veg", "egg"},
    "non_veg": set(DIETS),
    "nonveg": set(DIETS),
}
_DIET_TO_SAFETY = {"vegan": "vegan", "veg": "veg", "egg": "eggetarian", "nonveg": "non_veg"}

# user-entered allergy text (normalised) -> recipe allergen tags
_ALLERGY_TAGS = {
    "peanut": {"peanut"}, "groundnut": {"peanut"},
    "tree nut": {"tree_nut"}, "nut": {"tree_nut", "peanut"},
    "almond": {"tree_nut"}, "cashew": {"tree_nut"}, "walnut": {"tree_nut"}, "pistachio": {"tree_nut"},
    "milk": {"milk"}, "dairy": {"milk"}, "lactose": {"milk"},
    "egg": {"egg"},
    "gluten": {"gluten", "wheat"}, "wheat": {"gluten", "wheat"},
    "soy": {"soy"}, "soya": {"soy"},
    "fish": {"fish"}, "shellfish": {"shellfish"}, "sesame": {"sesame"}, "mustard": {"mustard"},
}
_ALLERGY_EXTRA_WORDS = {
    "wheat": {"wheat", "atta", "maida", "roti", "chapati", "phulka", "paratha", "naan", "bread", "semolina", "suji", "rava", "dalia"},
    "lactose": safety.DAIRY,
    "nut": {"almond", "cashew", "walnut", "pistachio", "hazelnut", "pecan", "badam", "kaju", "peanut", "groundnut"},
}

# keyword -> allergen implied by an ingredient (used to validate the dataset: declared allergens must cover these)
_IMPLIED = {
    "milk": safety.DAIRY,
    "egg": safety.EGG,
    "peanut": {"peanut", "groundnut", "moongphali"},
    "tree_nut": {"almond", "cashew", "walnut", "pistachio", "hazelnut", "pecan", "badam", "kaju"},
    "soy": {"soy", "soya", "tofu", "edamame"},
    "fish": {"fish", "salmon", "tuna", "pomfret", "rohu", "surmai", "bombil"},
    "shellfish": {"prawn", "shrimp", "crab", "lobster"},
    "sesame": {"sesame", "til", "tahini"},
    "mustard": {"mustard", "sarson"},
}
_WHEAT_WORDS = {"wheat", "atta", "maida", "roti", "chapati", "phulka", "paratha", "naan", "bread", "semolina", "suji", "rava",
                "pasta", "noodles", "vermicelli", "pav", "bun", "tortilla", "dalia", "seviyan"}
_NOT_ALLERGEN_PHRASES = ("coconut milk", "almond milk", "soy milk", "soya milk", "oat milk", "peanut butter", "butter bean",
                         "cocoa butter", "coconut cream", "milk thistle", "soy sauce", "buckwheat",
                         "bajra roti", "jowar roti", "ragi roti", "makki roti", "rice roti", "bajra bhakri", "jowar bhakri")


# ------------------------------------------------------------------------------------------ data model
@dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    description: str
    meal_types: tuple[str, ...]
    diet: str
    allergens: frozenset[str]
    tags: frozenset[str]  # dataset tags plus derived ones (spicy, low_oil, quick, high_protein)
    prep_minutes: int
    servings_note: str
    ingredients: tuple[str, ...]
    steps: tuple[str, ...]
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fibre_g: float
    tokens: frozenset[str]  # name + ingredients, lower-case, plural-tolerant
    blob: str
    main: str
    jain_ok: bool = False  # no onion, garlic, root vegetables, mushroom, brinjal, honey, egg or meat
    og_free: bool = False  # no onion or garlic

    @property
    def protein_density(self) -> float:
        return self.protein_g * 4 / self.kcal if self.kcal else 0.0


def _tokens(text: str) -> frozenset[str]:
    return frozenset(safety._tokenize(text))


# Onion/garlic words (English + common Indian names) and the wider Jain list (root vegetables, fungi, brinjal, honey).
ONION_GARLIC = {"onion", "onions", "garlic", "pyaz", "pyaaz", "piyaz", "lehsun", "lahsun", "lasun", "shallot", "shallots",
                "kanda", "leek", "leeks", "scallion", "scallions"}
JAIN_AVOID = ONION_GARLIC | {
    "potato", "potatoes", "aloo", "alu", "batata", "carrot", "carrots", "gajar", "beetroot", "beetroots", "beet", "beets",
    "radish", "radishes", "mooli", "turnip", "turnips", "shalgam", "ginger", "adrak", "yam", "suran", "jimikand", "arbi",
    "colocasia", "taro", "mushroom", "mushrooms", "brinjal", "brinjals", "baingan", "eggplant", "honey", "shakarkandi",
    "ratalu", "kand",
}
# dried ginger is accepted in Jain cooking; strip these phrases before checking
_JAIN_OK_PHRASES = ("dry ginger", "dried ginger", "ginger powder", "saunth", "sonth")


def _jain_ok(name: str, ingredients, diet: str) -> bool:
    if diet not in ("vegan", "veg"):
        return False
    text = (name + " " + " ".join(ingredients)).lower()
    for ph in _JAIN_OK_PHRASES:
        text = text.replace(ph, " ")
    return not (JAIN_AVOID & _tokens(text))


def _og_free(name: str, ingredients) -> bool:
    return not (ONION_GARLIC & _tokens(name + " " + " ".join(ingredients)))


_MAIN_WORDS = {
    "paneer": "paneer", "tofu": "tofu", "soya": "soya", "soy": "soya", "chicken": "chicken", "egg": "egg", "eggs": "egg",
    "anda": "egg", "omelette": "egg", "omelet": "egg", "bhurji": "egg", "fish": "fish", "prawn": "prawn", "prawns": "prawn", "shrimp": "prawn",
    "mutton": "mutton", "keema": "mutton", "rajma": "rajma", "chana": "chana", "chole": "chana", "chickpea": "chana",
    "chickpeas": "chana", "moong": "moong", "masoor": "masoor", "toor": "toor", "arhar": "toor", "urad": "urad",
    "lentil": "dal", "lentils": "dal", "dal": "dal", "oats": "oats", "oat": "oats", "poha": "poha", "upma": "upma",
    "idli": "idli", "dosa": "dosa", "uttapam": "dosa", "dhokla": "besan", "besan": "besan", "thepla": "wheat",
    "khichdi": "khichdi", "biryani": "rice", "pulao": "rice", "rice": "rice", "roti": "wheat", "paratha": "wheat",
    "ragi": "ragi", "jowar": "jowar", "bajra": "bajra", "millet": "millet", "quinoa": "quinoa", "dalia": "dalia",
    "potato": "potato", "aloo": "potato", "spinach": "spinach", "palak": "spinach", "cauliflower": "cauliflower",
    "gobi": "cauliflower", "mushroom": "mushroom", "mushrooms": "mushroom", "peas": "peas", "matar": "peas",
    "bhindi": "okra", "okra": "okra", "brinjal": "brinjal", "baingan": "brinjal", "cabbage": "cabbage",
    "carrot": "carrot", "beetroot": "beetroot", "pumpkin": "pumpkin", "lauki": "bottle gourd", "gourd": "gourd",
    "tomato": "tomato", "corn": "corn", "sprouts": "sprouts", "curd": "curd", "dahi": "curd", "yogurt": "curd",
    "banana": "banana", "apple": "apple", "sweet": "sweet potato", "bread": "bread", "sandwich": "bread",
    "makhana": "makhana", "peanut": "peanut", "peanuts": "peanut", "sabudana": "sabudana", "bhel": "puffed rice",
    "murmura": "puffed rice", "semolina": "rava", "rava": "rava", "suji": "rava", "vermicelli": "vermicelli",
    "pasta": "pasta", "noodles": "noodles", "smoothie": "smoothie", "lassi": "curd", "raita": "curd",
}


def _main_ingredient(name: str, ingredients) -> str:
    for w in _ordered_words(name):
        if w in _MAIN_WORDS:
            return _MAIN_WORDS[w]
    for line in ingredients:
        for w in _ordered_words(line):
            if w in _MAIN_WORDS:
                return _MAIN_WORDS[w]
    words = _ordered_words(name)
    return words[0] if words else name.lower()


def _ordered_words(text: str) -> list[str]:
    text = text.lower()
    for ch in ",.()/-":
        text = text.replace(ch, " ")
    return text.split()


_SPICY_WORDS = ("chilli", "chili", "mirchi", "masala", "pepper", "schezwan", "peri peri", "tikka", "curry")


def _oil_tsp(ingredients) -> float:
    total = 0.0
    for line in ingredients:
        low = line.lower()
        if not re.search(r"\b(oil|ghee|butter)\b", low) or "peanut butter" in low and "oil" not in low:
            continue
        m = _LEAD.match(low)
        if not m:
            total += 1.0
            continue
        qty = _to_fraction(m.group(1))
        unit = m.group(2).split()[0] if m.group(2).split() else ""
        total += float(qty) * (3 if unit.startswith("tbsp") else 1)
    return total


def _derive_tags(d: dict, tokens: frozenset[str], blob: str) -> frozenset[str]:
    tags = set(d.get("tags", []))
    if d["prep_minutes"] <= 15:
        tags.add("quick")
    if d["protein_g"] >= 20 or d["protein_g"] * 4 >= 0.25 * d["kcal"]:
        tags.add("high_protein")
    if d["fibre_g"] >= 7:
        tags.add("high_fibre")
    if any(w in blob for w in _SPICY_WORDS):
        tags.add("spicy")
    if _oil_tsp(d["ingredients"]) <= 1.0:
        tags.add("low_oil")
    return frozenset(tags)


# ------------------------------------------------------------------------------------------ validation / loading
def implied_allergens(ingredients, name: str = "") -> set[str]:
    text = (name + " " + " ".join(ingredients)).lower()
    for phrase in _NOT_ALLERGEN_PHRASES:
        text = text.replace(phrase, " ")
    toks = _tokens(text)
    found = {a for a, words in _IMPLIED.items() if words & toks}
    if _WHEAT_WORDS & toks:
        found.add("wheat")
    return found


def validate_recipe(d: dict) -> list[str]:
    """Returns a list of problems; empty means the recipe is usable."""
    p: list[str] = []
    try:
        name = d["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 90:
            p.append("bad name")
        if not isinstance(d["description"], str) or not d["description"] or len(d["description"]) > 200:
            p.append("bad description")
        mts = d["meal_types"]
        if not mts or any(t not in MEAL_TYPES for t in mts):
            p.append("bad meal_types")
        if d["diet"] not in DIETS:
            p.append("bad diet")
        if not set(d["allergens"]) <= ALLERGENS:
            p.append(f"unknown allergens {set(d['allergens']) - ALLERGENS}")
        if not 0 <= int(d["prep_minutes"]) <= 90:
            p.append("bad prep_minutes")
        ing = d["ingredients"]
        if not 4 <= len(ing) <= 12 or any(not isinstance(i, str) or not i.strip() or len(i) > 120 for i in ing):
            p.append("bad ingredients")
        steps = d["steps"]
        if not 3 <= len(steps) <= 8 or any(not isinstance(s, str) or not s.strip() or len(s) > 250 for s in steps):
            p.append("bad steps")
        if not d["servings_note"]:
            p.append("missing servings_note")
        for k in ("kcal", "protein_g", "carbs_g", "fat_g", "fibre_g"):
            if not isinstance(d[k], (int, float)) or d[k] < 0:
                p.append(f"bad {k}")
        if p:
            return p
        if not 30 <= d["kcal"] <= 1800:
            p.append("kcal out of range")
        energy = 4 * d["protein_g"] + 4 * d["carbs_g"] + 9 * d["fat_g"]
        if abs(energy - d["kcal"]) > MACRO_TOLERANCE * d["kcal"]:
            p.append(f"macro energy {energy} vs kcal {d['kcal']}")
        missing = implied_allergens(ing, name) - set(d["allergens"])
        if missing and not (missing == {"wheat"} and "gluten" in d["allergens"]):
            p.append(f"undeclared allergens {sorted(missing)}")
        blob = f"{name} {d['description']} {' '.join(ing)}".lower()
        if any(c in blob for c in safety.FORBIDDEN_CLAIMS):
            p.append("forbidden claim wording")
        toks = _tokens(blob)
        bad = safety.forbidden_for_diet(_DIET_TO_SAFETY[d["diet"]]) & toks
        if bad:
            p.append(f"diet {d['diet']} contains {sorted(bad)}")
        if d["diet"] != "nonveg" and safety.MEAT & toks:
            p.append("meat in non-meat recipe")
    except (KeyError, TypeError, ValueError) as exc:
        p.append(f"malformed: {exc!r}")
    return p


def _build(d: dict) -> Recipe:
    blob = f"{d['name']} {' '.join(d['ingredients'])}".lower()
    tokens = _tokens(blob)
    return Recipe(
        name=d["name"].strip(), description=d["description"].strip(), meal_types=tuple(d["meal_types"]), diet=d["diet"],
        allergens=frozenset(d["allergens"]), tags=_derive_tags(d, tokens, blob), prep_minutes=int(d["prep_minutes"]),
        servings_note=d["servings_note"].strip(), ingredients=tuple(d["ingredients"]), steps=tuple(d["steps"]),
        kcal=float(d["kcal"]), protein_g=float(d["protein_g"]), carbs_g=float(d["carbs_g"]), fat_g=float(d["fat_g"]),
        fibre_g=float(d["fibre_g"]), tokens=tokens, blob=blob, main=_main_ingredient(d["name"], d["ingredients"]),
        jain_ok=_jain_ok(d["name"], d["ingredients"], d["diet"]), og_free=_og_free(d["name"], d["ingredients"]),
    )


def file_recipe_dicts() -> list[tuple[str, dict]]:
    """Raw recipe dicts from app/meal_data/*.py as (module name, dict). Used to seed the database and as a fallback."""
    out: list[tuple[str, dict]] = []
    for info in sorted(pkgutil.iter_modules(meal_data.__path__), key=lambda i: i.name):
        if info.name.startswith("__"):
            continue
        try:
            mod = importlib.import_module(f"{meal_data.__name__}.{info.name}")
            out.extend((info.name, d) for d in list(mod.RECIPES))
        except Exception:  # a broken data file must not take the API down
            log.exception("meal_data.%s could not be loaded", info.name)
    return out


def build_recipes(raw: list[tuple[str, dict]]) -> tuple[list[Recipe], list[tuple[str, list[str]]], dict[str, str]]:
    """Validates and builds recipes. Returns (valid recipes, [(name, problems)] for skipped ones, name -> source)."""
    ok: list[Recipe] = []
    skipped: list[tuple[str, list[str]]] = []
    origin: dict[str, str] = {}
    seen: set[str] = set()
    for src, d in raw:
        label = d.get("name", "?") if isinstance(d, dict) else "?"
        problems = validate_recipe(d) if isinstance(d, dict) else ["not a dict"]
        if not problems and d["name"].strip().lower() in seen:
            problems.append("duplicate name")
        if problems:
            log.error("recipe %s (%s): skipping: %s", label, src, "; ".join(problems))
            skipped.append((label, problems))
            continue
        seen.add(d["name"].strip().lower())
        origin[d["name"].strip()] = src
        ok.append(_build(d))
    return ok, skipped, origin


def load_recipes() -> tuple[list[Recipe], list[tuple[str, list[str]]], dict[str, str]]:
    """Returns (valid recipes, [(name, problems)] for skipped ones, name -> module). Reads the data files."""
    return build_recipes(file_recipe_dicts())


def install_recipes(raw: list[tuple[str, dict]]) -> int:
    """Replaces the in-memory recipe set (in place, so existing references stay valid) with `raw` after validation.
    Does nothing and returns 0 if no recipe is valid. Returns the number of recipes now served."""
    ok, skipped, origin = build_recipes(raw)
    if not ok:
        return 0
    RECIPES[:] = ok
    SKIPPED[:] = skipped
    ORIGIN.clear()
    ORIGIN.update(origin)
    BY_NAME.clear()
    BY_NAME.update({r.name.lower(): r for r in ok})
    return len(ok)


# ------------------------------------------------------------------------------------------ eligibility
def _norm_allergy(text: str) -> str:
    k = text.strip().lower().replace("_", " ").replace("-", " ")
    k = " ".join(k.split())
    if k.endswith("s") and not k.endswith("ss") and len(k) > 3:
        k = k[:-1]
    if k in ("tree nuts", "treenut"):
        k = "tree nut"
    return k


class _Filter:
    """Pre-computed view of a profile's restrictions; cheap to apply to many recipes."""

    def __init__(self, profile):
        self.diet_type = getattr(profile, "diet_type", "non_veg")
        r = getattr(profile, "restrictions", None) or {}
        self.allergies = [a for a in (r.get("allergies") or []) if a and a.strip()]
        self.dislikes = [d.strip().lower() for d in (r.get("dislikes") or []) if d and d.strip()]
        self.allowed_diets = _DIET_ALLOWED.get(self.diet_type, _DIET_ALLOWED["veg"])
        self.jain = bool(r.get("jain"))
        self.no_onion_garlic = bool(r.get("no_onion_garlic"))
        self.tags: set[str] = set()
        self.words: set[str] = set()
        for a in self.allergies:
            key = _norm_allergy(a)
            self.tags |= _ALLERGY_TAGS.get(key, set())
            raw = a.strip().lower()
            self.words |= safety.ALLERGEN_ALIASES.get(raw, set()) | safety.ALLERGEN_ALIASES.get(key, set()) | _ALLERGY_EXTRA_WORDS.get(key, set())
            self.words |= set(_tokens(key))

    def ok(self, r: Recipe) -> bool:
        if r.diet not in self.allowed_diets:
            return False
        if self.jain and not r.jain_ok:
            return False
        if self.no_onion_garlic and not r.og_free:
            return False
        if self.tags & r.allergens or self.words & r.tokens:
            return False
        for d in self.dislikes:
            if " " in d:
                if d in r.blob:
                    return False
            elif d in r.tokens or (d.endswith("s") and d[:-1] in r.tokens):
                return False
        # final guard: the exact check the API applies to every meal it returns
        return not safety.violations(to_meal(r), self.diet_type, self.allergies, self.dislikes)


def eligible(recipe: Recipe, profile) -> bool:
    return _Filter(profile).ok(recipe)


def eligible_pool(profile, meal_type: str) -> list[Recipe]:
    f = _Filter(profile)
    return [r for r in RECIPES if meal_type in r.meal_types and f.ok(r)]


# ------------------------------------------------------------------------------------------ portions
_NUM = r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_LEAD = re.compile(rf"^\s*{_NUM}\s*(.*)$")
_MEASURE_UNITS = ("cup", "cups", "tbsp", "tsp", "katori", "katoris", "bowl", "glass", "tablespoon", "teaspoon", "tablespoons", "teaspoons")
_COUNT_UNITS_EXACT = ("g", "gm", "gram", "grams", "ml", "kg", "l")


def _to_fraction(s: str) -> Fraction:
    parts = s.split()
    total = Fraction(0)
    for p in parts:
        total += Fraction(p)
    return total


def _fmt_fraction(q: Fraction) -> str:
    whole = q.numerator // q.denominator
    rest = q - whole
    if rest == 0:
        return str(whole)
    return f"{whole} {rest}" if whole else str(rest)


def _scale_line(line: str, factor: Fraction) -> str | None:
    """Scales the leading quantity of one ingredient line. Returns None when that cannot be done exactly."""
    m = _LEAD.match(line)
    if not m:
        return line  # no leading quantity ("salt to taste", "a pinch of ..."): leave as is
    rest = m.group(2)
    if re.match(r"[-–]\s*\d", rest) or re.search(r"\d", rest):
        return None  # range ("2-3") or a second number (e.g. "(about 80 g)") that we would leave stale
    base = _to_fraction(m.group(1))
    qty = base * factor
    words = rest.lower().replace(",", " ").split()
    unit = words[0].strip(",") if words else ""
    if unit in _COUNT_UNITS_EXACT:
        if round(qty) == 0:
            return None
        text = str(round(qty))
    elif unit in ("tsp", "teaspoon", "teaspoons") and base <= 1:
        return line  # a pinch-level seasoning: left as written
    else:
        if unit in _MEASURE_UNITS:
            step = 8
        elif {"egg", "eggs", "slice", "slices", "piece", "pieces", "idli", "idlis", "dosa", "dosas", "ladle", "ladles"} & set(words[:2]):
            step = 1  # whole items only
        elif {"roti", "rotis", "phulka", "phulkas", "paratha", "parathas", "chapati", "chapatis", "tortilla", "thepla", "theplas"} & set(words[:3]):
            step = 2
        else:
            step = 4
        if (qty * step).denominator != 1 or qty == 0:
            return None
        text = _fmt_fraction(qty)
    return f"{text} {rest}".strip()


def scaled_ingredients(r: Recipe, factor: float) -> list[str] | None:
    if factor == 1.0:
        return list(r.ingredients)
    fr = Fraction(factor).limit_denominator(8)
    out = []
    for line in r.ingredients:
        s = _scale_line(line, fr)
        if s is None:
            return None
        out.append(s)
    return out


def _scalable(r: Recipe, factor: float) -> bool:
    return scaled_ingredients(r, factor) is not None


def slot_target(day_kcal: float, meal_type: str, slots=None) -> float:
    slots = list(slots) if slots else list(MEAL_TYPES)
    if meal_type not in slots:
        slots.append(meal_type)
    return day_kcal * SHARES[meal_type] / sum(SHARES[s] for s in slots)


def choose_portion(r: Recipe, target: float, max_kcal: float | None = None) -> float:
    best = 1.0
    if target > 0 and abs(r.kcal - target) > 0.2 * target:
        best = min(PORTIONS, key=lambda f: abs(r.kcal * f - target))
    if max_kcal and r.kcal * best > max_kcal:
        fits = [f for f in PORTIONS if f <= best and r.kcal * f <= max_kcal]
        best = max(fits) if fits else min(PORTIONS)
    if best != 1.0 and not _scalable(r, best):
        best = 1.0
    return best


def _fmt_factor(f: float) -> str:
    return f"{f:g}"


def to_meal(r: Recipe, factor: float = 1.0) -> Meal:
    ing = scaled_ingredients(r, factor)
    if ing is None:
        factor, ing = 1.0, list(r.ingredients)
    label = f" Serving: {r.servings_note}." if factor == 1.0 else f" Serving: {_fmt_factor(factor)}x of {r.servings_note}."
    desc = r.description
    if len(desc) + len(label) > 300:
        desc = desc[: 300 - len(label) - 1].rstrip() + "…"
    return Meal(
        name=r.name, description=desc + label, ingredients=ing, steps=list(r.steps),
        kcal=round(r.kcal * factor), protein_g=round(r.protein_g * factor, 1), carbs_g=round(r.carbs_g * factor, 1),
        fat_g=round(r.fat_g * factor, 1), fibre_g=round(r.fibre_g * factor, 1), prep_minutes=r.prep_minutes,
    )


# ------------------------------------------------------------------------------------------ scoring and selection
@dataclass(frozen=True)
class Candidate:
    recipe: Recipe
    factor: float
    score: float

    @property
    def kcal(self) -> float:
        return self.recipe.kcal * self.factor


def _phrase_hit(phrase: str, r: Recipe) -> bool:
    words = [w for w in _ordered_words(phrase) if w]
    if not words:
        return False
    return all(w in r.tokens or (w.endswith("s") and w[:-1] in r.tokens) for w in words)


def rank(
    pool: list[Recipe], rng: random.Random, *, target_kcal: float, goal: str = "maintain", tags=(), max_minutes: int | None = None,
    max_kcal: float | None = None, home=(), exclude_names=(), avoid_mains=(), hard=None, bonus=None,
    require_any_tag: bool = False,
) -> list[Candidate]:
    """Filters the pool, scores each recipe and returns candidates best first (with seeded jitter for variety)."""
    exclude = {n.strip().lower() for n in exclude_names}
    tags = set(tags)
    protein_w = {"build_muscle": 8.0, "lose_weight": 6.0}.get(goal, 2.0)
    fibre_w = 0.1 if goal in ("lose_weight", "eat_healthier") else 0.03
    out: list[Candidate] = []
    for r in pool:
        if r.name.lower() in exclude:
            continue
        if max_minutes is not None and r.prep_minutes > max_minutes:
            continue
        matched = len(tags & r.tags)
        if tags and require_any_tag and matched == 0:
            continue
        f = choose_portion(r, target_kcal, max_kcal)
        kcal = r.kcal * f
        if max_kcal is not None and kcal > max_kcal:
            continue
        if hard is not None and not hard(r, f):
            continue
        closeness = 1 - min(1.0, abs(kcal - target_kcal) / target_kcal) if target_kcal else 0.0
        s = 3.0 * matched + 4.0 * closeness + protein_w * r.protein_density + fibre_w * min(r.fibre_g * f, 10)
        s += 4.0 * min(sum(_phrase_hit(h, r) for h in home), 2)
        if max_minutes:
            s += 0.5 * (1 - r.prep_minutes / max_minutes)
        if r.main in avoid_mains:
            s -= 3.0
        if bonus is not None:
            s += bonus(r, f)
        s += rng.random() * JITTER
        out.append(Candidate(r, f, s))
    out.sort(key=lambda c: (-c.score, c.recipe.name))
    return out


def _top(cands: list[Candidate], n: int) -> list[Candidate]:
    """Best n, preferring different main ingredients."""
    chosen: list[Candidate] = []
    mains: set[str] = set()
    for c in cands:
        if c.recipe.main not in mains:
            chosen.append(c)
            mains.add(c.recipe.main)
            if len(chosen) == n:
                return chosen
    for c in cands:
        if c not in chosen:
            chosen.append(c)
            if len(chosen) == n:
                break
    return chosen


class NoMealFound(Exception):
    """No recipe satisfies the profile's restrictions (even after relaxing preferences)."""


# Meal Finder "food type" chip -> recipe diets wanted (always intersected with what the profile allows).
FOOD_TYPE_DIETS = {
    "veg": {"vegan", "veg"},
    "vegan": {"vegan"},
    "egg": {"egg"},
    "non_veg": {"nonveg"},
    "jain": {"vegan", "veg"},
}
CUISINE_TAGS = {
    "south_indian": {"south_indian", "kerala", "hyderabadi", "chettinad"},
    "north_indian": {"north_indian", "punjabi", "kashmiri", "rajasthani"},
}


def narrow_pool(pool: list[Recipe], food_type: str | None = None, cuisine: str | None = None, n: int = 3) -> list[Recipe]:
    """Applies the finder's food-type and cuisine chips. Never widens the profile's pool; a chip that would leave
    too few recipes is ignored (cuisine) or relaxed to the closest safe set (food type)."""
    if food_type in FOOD_TYPE_DIETS:
        want = FOOD_TYPE_DIETS[food_type]
        sub = [r for r in pool if r.diet in want and (food_type != "jain" or r.jain_ok)]
        if not sub and food_type in ("egg", "non_veg"):
            sub = list(pool)  # profile does not allow it (e.g. a veg profile tapping Non-veg): stay within the profile
        if food_type == "jain":
            pool = sub  # Jain is a hard rule, never relaxed
        elif sub:
            pool = sub
    if cuisine in CUISINE_TAGS:
        sub = [r for r in pool if r.tags & CUISINE_TAGS[cuisine]]
        if len(sub) >= n:
            pool = sub
    return pool


def find_meals(
    profile, day_kcal: float, meal_type: str, rng: random.Random, *, tags=(), max_minutes: int | None = None,
    max_kcal: int | None = None, home=(), n: int = 3, slots=None, food_type: str | None = None, cuisine: str | None = None,
) -> list[Meal]:
    """Meal Finder. Relaxes tags first, then max_minutes, then (slightly) max_kcal before giving up."""
    pool = narrow_pool(eligible_pool(profile, meal_type), food_type, cuisine, n)
    if not pool:
        raise NoMealFound(meal_type)
    target = slot_target(day_kcal, meal_type, slots)
    if max_kcal:
        target = min(target, max_kcal)
    goal = getattr(profile, "goal", "maintain")
    levels = [
        {"tags": tags, "max_minutes": max_minutes, "max_kcal": max_kcal, "require_any_tag": True},
        {"tags": (), "max_minutes": max_minutes, "max_kcal": max_kcal},
        {"tags": (), "max_minutes": None, "max_kcal": max_kcal},
        {"tags": (), "max_minutes": None, "max_kcal": max_kcal * 1.1 if max_kcal else None},
    ]
    for lv in levels:
        cands = rank(pool, rng, target_kcal=target, goal=goal, home=home, **lv)
        if cands:
            chosen = _top(cands, n)
            if len(chosen) < n and tags and lv is levels[0]:  # few tag matches: top up with the best of the rest
                rest = rank(pool, rng, target_kcal=target, goal=goal, home=home, exclude_names=[c.recipe.name for c in chosen],
                            max_minutes=lv["max_minutes"], max_kcal=lv["max_kcal"])
                chosen += _top(rest, n - len(chosen))
            return [to_meal(c.recipe, c.factor) for c in chosen]
    raise NoMealFound(meal_type)


def build_plan(
    profile, day_kcal: float, days: int, slots: list[str], rng: random.Random,
) -> list[list[tuple[str, Meal]]]:
    """Multi-day plan. No recipe repeats inside the plan unless a slot's pool is exhausted (never twice in one day);
    the same main ingredient is avoided on consecutive days and inside a day."""
    pools = {s: eligible_pool(profile, s) for s in slots}
    if any(not p for p in pools.values()):
        raise NoMealFound("plan")
    goal = getattr(profile, "goal", "maintain")
    used: set[str] = set()
    prev_mains: set[str] = set()
    out: list[list[tuple[str, Meal]]] = []
    # fill the scarcest slot first so a small pool is not starved by shared recipes
    order = sorted(slots, key=lambda s: len(pools[s]))
    for _ in range(days):
        day_names: set[str] = set()
        day_mains: set[str] = set()
        picked: dict[str, tuple[Meal, str]] = {}
        for s in order:
            pool = [r for r in pools[s] if r.name.lower() not in day_names]
            if not pool:
                raise NoMealFound("plan")
            fresh = [r for r in pool if r.name.lower() not in used]
            if not fresh:
                used -= {r.name.lower() for r in pools[s]}
                fresh = pool
            cands = rank(
                fresh, rng, target_kcal=slot_target(day_kcal, s, slots), goal=goal, avoid_mains=prev_mains | day_mains,
            )
            c = cands[0]
            picked[s] = (to_meal(c.recipe, c.factor), c.recipe.main)
            day_names.add(c.recipe.name.lower())
            day_mains.add(c.recipe.main)
            used.add(c.recipe.name.lower())
        out.append([(s, picked[s][0]) for s in slots])
        prev_mains = day_mains
    return out


@dataclass(frozen=True)
class CurrentMeal:
    name: str
    kcal: float | None = None
    protein_g: float | None = None
    prep_minutes: int | None = None


def replace_meals(
    profile, day_kcal: float, meal_type: str, rng: random.Random, reason: str, current: CurrentMeal,
    exclude_names=(), slots=None, n: int = 3,
) -> list[Meal]:
    pool = eligible_pool(profile, meal_type)
    target = slot_target(day_kcal, meal_type, slots)
    goal = getattr(profile, "goal", "maintain")
    known = BY_NAME.get(current.name.strip().lower())
    cur_kcal = current.kcal if current.kcal is not None else (known.kcal if known else None)
    cur_protein = current.protein_g if current.protein_g is not None else (known.protein_g if known else None)
    cur_prep = current.prep_minutes if current.prep_minutes is not None else (known.prep_minutes if known else None)
    cur_main = known.main if known else _main_ingredient(current.name, [])
    exclude = [current.name, *exclude_names]
    max_kcal = None
    hard = bonus = None

    if reason == "dont_like":
        def hard(r, f):
            return r.main != cur_main
    elif reason == "missing_ingredient":
        def hard(r, f):
            return r.main != cur_main

        def bonus(r, f):
            return 0.4 * (9 - len(r.ingredients)) + (1.0 if {"budget", "one_pot", "quick"} & r.tags else 0.0)
    elif reason == "no_time":
        limit = (cur_prep - 1) if cur_prep else 15

        def hard(r, f):
            return r.prep_minutes <= limit

        def bonus(r, f):
            return -0.25 * r.prep_minutes
    elif reason == "lighter":
        ref = cur_kcal or target
        max_kcal = ref * 0.9
        target = min(target, ref * 0.85)

        def bonus(r, f):
            return (1.0 if {"light", "low_carb", "high_fibre", "low_oil"} & r.tags else 0.0) + 0.2 * min(r.fibre_g * f, 8)
    elif reason == "more_protein":
        def hard(r, f):
            if cur_protein is not None:
                return r.protein_g * f >= cur_protein + 4
            return r.protein_density >= 0.25

        def bonus(r, f):
            return 10 * r.protein_density

    attempts = [{"hard": hard, "max_kcal": max_kcal}, {"hard": None, "max_kcal": max_kcal}, {"hard": None, "max_kcal": None}]
    chosen: list[Candidate] = []
    for a in attempts:  # strict reason filter first, then top up with the best of the relaxed pools
        cands = rank(pool, rng, target_kcal=target, goal=goal, exclude_names=exclude, bonus=bonus, **a)
        if reason == "lighter" and a["max_kcal"] is None and cur_kcal:
            cands = [c for c in cands if c.kcal < cur_kcal] or cands
        have = {c.recipe.name for c in chosen}
        chosen += _top([c for c in cands if c.recipe.name not in have], n - len(chosen))
        if len(chosen) >= n:
            break
    if not chosen:
        raise NoMealFound(meal_type)
    return [to_meal(c.recipe, c.factor) for c in chosen]


def planned(meal_type: str, meal: Meal) -> PlannedMeal:
    return PlannedMeal(**meal.model_dump(), meal_type=meal_type)


def coverage() -> dict[tuple[str, str], int]:
    """Number of recipes per (diet filter, meal_type) that a user of that diet could be served."""
    out = {}
    for diet, allowed in (("vegan", {"vegan"}), ("veg", {"vegan", "veg"}), ("eggetarian", {"vegan", "veg", "egg"}), ("non_veg", set(DIETS))):
        for mt in MEAL_TYPES:
            out[(diet, mt)] = sum(1 for r in RECIPES if r.diet in allowed and mt in r.meal_types)
    return out


RECIPES, SKIPPED, ORIGIN = load_recipes()
BY_NAME = {r.name.lower(): r for r in RECIPES}
if not RECIPES:
    log.error("meal engine has no recipes")

"""Deterministic grocery list: aggregates ingredient lines of planned meals. Best-effort parsing; never invents quantities."""

import re
from fractions import Fraction

from app.ai.schemas import GroceryGroup, GroceryItem

GROUP_ORDER = ["Vegetables", "Fruits", "Dairy and eggs", "Grains and flours", "Pulses", "Meat and fish", "Spices and oils", "Other"]
MAX_ITEMS = 60

_NUM = r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_LEAD = re.compile(rf"^\s*{_NUM}\s*(.*)$")
_PINCH = re.compile(r"^\s*(a\s+)?(pinch|handful|dash|sprig|bunch)(es)?\s+(of\s+)?(.*)$", re.IGNORECASE)

# unit spelling -> (canonical unit, factor to base unit). Base units: g, ml, and the unit itself for the rest.
_UNITS = {
    "g": ("g", 1), "gm": ("g", 1), "gram": ("g", 1), "grams": ("g", 1), "kg": ("g", 1000), "ml": ("ml", 1),
    "l": ("ml", 1000), "litre": ("ml", 1000), "litres": ("ml", 1000), "liter": ("ml", 1000),
    "cup": ("cup", 1), "cups": ("cup", 1), "tbsp": ("tbsp", 1), "tablespoon": ("tbsp", 1), "tablespoons": ("tbsp", 1),
    "tsp": ("tsp", 1), "teaspoon": ("tsp", 1), "teaspoons": ("tsp", 1), "katori": ("katori", 1), "bowl": ("bowl", 1),
    "slice": ("slice", 1), "slices": ("slice", 1), "clove": ("clove", 1), "cloves": ("clove", 1), "sprig": ("sprig", 1),
    "sprigs": ("sprig", 1), "glass": ("glass", 1), "glasses": ("glass", 1), "inch": ("inch", 1), "pinch": ("pinch", 1),
    "handful": ("handful", 1), "bunch": ("bunch", 1), "can": ("can", 1), "piece": ("piece", 1), "pieces": ("piece", 1),
}
_PLURAL_UNIT = {"cup": "cups", "slice": "slices", "clove": "cloves", "sprig": "sprigs", "glass": "glasses", "piece": "pieces",
                "katori": "katoris", "bowl": "bowls", "handful": "handfuls", "bunch": "bunches", "pinch": "pinches", "can": "cans"}

_SIZE_WORDS = {"small", "medium", "large", "big", "fresh", "ripe", "raw", "cooked", "boiled", "roasted", "chopped", "sliced",
               "diced", "grated", "minced", "finely", "thinly", "soaked", "whole", "mixed", "of", "a", "an", "the", "some",
               "peeled", "crushed", "ground", "dry", "dried", "cubed", "shredded", "washed", "mashed", "lightly", "heaped", "level"}

_PRE_EXCEPT = [
    ("coconut milk", "Other"), ("almond milk", "Other"), ("soy milk", "Other"), ("soya milk", "Other"), ("peanut butter", "Other"),
    ("butter bean", "Pulses"), ("bell pepper", "Vegetables"), ("lemon grass", "Vegetables"), ("lemongrass", "Vegetables"),
    ("curry leaf", "Vegetables"), ("curry leaves", "Vegetables"), ("coriander leaves", "Vegetables"), ("green chilli", "Vegetables"),
    ("green chili", "Vegetables"), ("chilli powder", "Spices and oils"), ("coriander seed", "Spices and oils"), ("cumin seed", "Spices and oils"),
]
_KEYWORDS: list[tuple[str, set[str]]] = [
    ("Spices and oils", {"powder", "masala", "salt", "oil", "turmeric", "haldi", "jeera", "cumin", "hing", "asafoetida", "cardamom",
                         "pepper", "cinnamon", "bay", "mustard", "fenugreek", "kasuri", "chaat", "amchur", "saffron",
                         "vinegar", "ajwain", "carom", "fennel", "saunf", "clove", "cloves", "spice", "spices", "paprika", "oregano",
                         "chilli", "chili", "flakes", "sauce", "tamarind", "imli"}),
    ("Meat and fish", {"chicken", "mutton", "lamb", "beef", "pork", "fish", "prawn", "prawns", "shrimp", "crab", "keema", "salmon",
                       "tuna", "pomfret", "rohu", "surmai", "bombil", "turkey", "sausage", "bacon"}),
    ("Dairy and eggs", {"milk", "paneer", "curd", "yogurt", "yoghurt", "dahi", "ghee", "butter", "cheese", "cream", "khoya", "lassi",
                        "buttermilk", "chaas", "whey", "egg", "eggs"}),
    ("Pulses", {"dal", "daal", "chana", "chole", "rajma", "lentil", "lentils", "chickpea", "chickpeas", "moong", "masoor", "toor",
                "urad", "arhar", "lobia", "beans", "soya", "soy", "tofu", "sprouts"}),
    ("Grains and flours", {"rice", "atta", "flour", "roti", "chapati", "phulka", "oats", "poha", "rava", "suji", "semolina", "bread",
                           "millet", "ragi", "jowar", "bajra", "besan", "maida", "pasta", "quinoa", "dalia", "vermicelli", "cornflour",
                           "noodles", "paratha", "naan", "tortilla", "idli", "dosa", "murmura", "sabudana", "pav", "bun", "makhana",
                           "cornmeal", "barley", "wheat", "thepla", "khakhra"}),
    ("Fruits", {"banana", "apple", "mango", "lemon", "lime", "papaya", "orange", "pomegranate", "berries", "strawberry", "blueberry",
                "grapes", "guava", "pineapple", "watermelon", "melon", "kiwi", "pear", "date", "dates", "raisin", "raisins", "fig", "figs",
                "coconut", "amla", "chikoo", "sapota"}),
    ("Vegetables", {"onion", "tomato", "potato", "spinach", "palak", "cauliflower", "gobi", "cabbage", "carrot", "beetroot", "capsicum",
                    "cucumber", "okra", "bhindi", "brinjal", "baingan", "eggplant", "pumpkin", "lauki", "gourd", "tori", "turai", "karela",
                    "mushroom", "mushrooms", "corn", "garlic", "ginger", "coriander", "mint", "pudina", "methi", "leaves", "leaf", "radish",
                    "mooli", "zucchini", "broccoli", "lettuce", "salad", "spring", "beans", "peas", "aloo", "matar", "sweet", "drumstick",
                    "tinda", "parwal", "arbi", "yam", "kale", "sarson", "saag", "greens", "chilli", "chili", "celery", "leek", "bean"}),
]
# vegetables that also appear as pulses / spices keywords: resolve explicitly by whole-name hints
_VEG_FIRST = ("green peas", "green beans", "french beans", "sweet potato", "sweet corn", "spring onion", "green chilli")


def _to_fraction(s: str) -> Fraction:
    return sum((Fraction(p) for p in s.split()), Fraction(0))


def _singular(word: str) -> str:
    w = word.lower()
    if w == "leaves":
        return "leaf"
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("oes"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
        return w[:-1]
    return w


def parse_line(line: str) -> tuple[str, str, str, float | None]:
    """Returns (merge key, display name, unit, quantity in base units or None when there is no number)."""
    text = re.sub(r"\([^)]*\)", " ", line).strip()
    text = text.split(",")[0].strip()
    pm = _PINCH.match(text)
    qty: float | None = None
    unit = ""
    if pm:
        unit, name_part = pm.group(2).lower(), pm.group(5)
        qty = 1.0
        unit = _UNITS.get(unit, (unit, 1))[0]
    else:
        m = _LEAD.match(text)
        if m:
            qty = float(_to_fraction(m.group(1)))
            rest = m.group(2).strip()
            first = rest.split()[0].lower().strip(".") if rest.split() else ""
            if first in _UNITS:
                unit, factor = _UNITS[first]
                qty *= factor
                rest = rest[len(rest.split()[0]):].strip()
            name_part = rest
        else:
            name_part = text
    name_part = re.sub(r"\b(to taste|as needed|as required|for garnish|for garnishing|for serving|optional)\b", " ", name_part, flags=re.IGNORECASE)
    words = [w for w in re.split(r"[\s]+", name_part.strip()) if w]
    words = [w for w in words if w.lower().strip(".") not in _SIZE_WORDS] or words
    name = " ".join(words).strip(" -.") or text
    key_words = [w.lower() for w in words]
    if key_words:
        key_words[-1] = _singular(key_words[-1])
    key = " ".join(key_words) or name.lower()
    return key, name, unit, qty


def classify(name: str) -> str:
    low = name.lower()
    for phrase, group in _PRE_EXCEPT:
        if phrase in low:
            return group
    if any(p in low for p in _VEG_FIRST) and "powder" not in low:
        return "Vegetables"
    toks = set(re.split(r"[^a-z]+", low)) | {_singular(t) for t in re.split(r"[^a-z]+", low)}
    for group, words in _KEYWORDS:
        if toks & words:
            return group
    return "Other"


def _fmt_qty(unit: str, qty: float) -> str:
    if unit == "g":
        return f"{qty / 1000:g} kg" if qty >= 1000 else f"{qty:g} g"
    if unit == "ml":
        return f"{qty / 1000:g} l" if qty >= 1000 else f"{qty:g} ml"
    fr = Fraction(qty).limit_denominator(4)
    whole = fr.numerator // fr.denominator
    rest = fr - whole
    n = f"{whole} {rest}" if whole and rest else (str(whole) if whole else str(rest))
    if not unit:
        return n
    u = unit if (fr <= 1 or unit not in _PLURAL_UNIT) else _PLURAL_UNIT[unit]
    return f"{n} {u}"


def build_grocery(ingredient_lists: list[list[str]]) -> list[GroceryGroup]:
    """Merges the same ingredient across meals; quantities are added when the unit matches, else listed side by side."""
    totals: dict[str, dict[str, float]] = {}
    display: dict[str, str] = {}
    to_taste: set[str] = set()
    for lines in ingredient_lists:
        for line in lines:
            if not line or not line.strip():
                continue
            key, shown, unit, qty = parse_line(line)
            if not key or key in ("water", "ice", "hot water", "warm water"):
                continue
            display.setdefault(key, shown[:1].upper() + shown[1:].lower())
            if qty is None:
                to_taste.add(key)
                totals.setdefault(key, {})
                continue
            bucket = totals.setdefault(key, {})
            bucket[unit] = bucket.get(unit, 0.0) + qty
    grouped: dict[str, list[GroceryItem]] = {g: [] for g in GROUP_ORDER}
    for key in sorted(totals):
        parts = [_fmt_qty(u, q) for u, q in sorted(totals[key].items(), key=lambda kv: (kv[0] == "", kv[0]))]
        quantity = " + ".join(parts) if parts else "to taste"
        if parts and key in to_taste:
            quantity += " + to taste"
        grouped[classify(key)].append(GroceryItem(name=display[key][:80], quantity=quantity[:60]))
    return [GroceryGroup(name=g, items=items[:MAX_ITEMS]) for g, items in grouped.items() if items]

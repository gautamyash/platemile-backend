from app.ai.safety import violations
from app.ai.schemas import Meal


def m(name, ings, kcal=300, p=15, c=40, f=8):
    return Meal(name=name, description="x", ingredients=ings, kcal=kcal, protein_g=p, carbs_g=c, fat_g=f, fibre_g=4, prep_minutes=10)


def test_vegan_blocks_dairy_and_honey():
    assert violations(m("Lassi", ["curd", "sugar"]), "vegan", [], [])
    assert violations(m("Bowl", ["oats", "honey"]), "vegan", [], [])


def test_eggetarian_allows_egg_blocks_meat():
    assert not violations(m("Omelette", ["egg", "onion"], f=10), "eggetarian", [], [])
    assert violations(m("Chicken curry", ["chicken"]), "eggetarian", [], [])


def test_allergy_alias_and_dislike():
    assert violations(m("Kaju katli", ["cashew"]), "veg", ["tree nut"], [])
    assert violations(m("Bhindi", ["okra", "bhindi"]), "veg", [], ["bhindi"])


def test_macro_mismatch_and_claims():
    assert "macro_mismatch" in violations(m("Salad", ["lettuce"], kcal=900, p=5, c=10, f=2), "veg", [], [])
    bad = Meal(name="Detox soup", description="cures everything", ingredients=["water"], kcal=100, protein_g=5, carbs_g=15, fat_g=2, fibre_g=1, prep_minutes=5)
    assert "claim" in violations(bad, "veg", [], [])

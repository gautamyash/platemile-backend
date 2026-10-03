import pytest

from app.nutrition import bmr_mifflin_st_jeor, calculate_targets


def test_bmr_known_values():
    # 70 kg, 175 cm, 30 y male: 10*70 + 6.25*175 - 150 + 5 = 1648.75
    assert bmr_mifflin_st_jeor("male", 70, 175, 30) == pytest.approx(1648.75)
    # 60 kg, 165 cm, 30 y female: 600 + 1031.25 - 150 - 161 = 1320.25
    assert bmr_mifflin_st_jeor("female", 60, 165, 30) == pytest.approx(1320.25)


def test_weight_loss_has_deficit_but_not_below_floor():
    t = calculate_targets(
        sex="female", weight_kg=60, height_cm=165, age=30, activity_level="light", goal="lose_weight"
    )
    assert t.kcal < t.tdee
    assert t.kcal >= 1200


def test_floor_is_applied_for_small_sedentary_adults():
    t = calculate_targets(
        sex="female", weight_kg=45, height_cm=150, age=40, activity_level="sedentary", goal="lose_weight"
    )
    assert t.kcal == 1200
    assert "calorie_floor_applied" in t.notes


def test_under_18_gets_no_deficit():
    t = calculate_targets(
        sex="male", weight_kg=60, height_cm=170, age=16, activity_level="active", goal="lose_weight"
    )
    assert t.kcal == t.tdee
    assert "under_18_no_deficit" in t.notes


def test_muscle_gain_adds_surplus():
    t = calculate_targets(
        sex="male", weight_kg=70, height_cm=175, age=25, activity_level="active", goal="build_muscle"
    )
    assert t.kcal > t.tdee


def test_macros_add_up_to_target_calories():
    t = calculate_targets(
        sex="male", weight_kg=80, height_cm=180, age=28, activity_level="active", goal="maintain"
    )
    total = t.protein_g * 4 + t.carbs_g * 4 + t.fat_g * 9
    assert abs(total - t.kcal) <= 10


@pytest.mark.parametrize("bad", [{"sex": "x"}, {"activity_level": "none"}, {"weight_kg": 0}])
def test_invalid_input_raises(bad):
    args = {"sex": "male", "weight_kg": 70, "height_cm": 175, "age": 30, "activity_level": "light", "goal": "maintain"}
    args.update(bad)
    with pytest.raises(ValueError):
        calculate_targets(**args)

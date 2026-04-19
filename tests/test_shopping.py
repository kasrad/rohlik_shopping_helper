"""
Tests for _auto_suggest_quantity in shopping.py.

Heavy imports (agents.mcp_agent, pantry) are mocked before importing shopping
so this module can run in a plain pytest environment without env vars or
MCP infrastructure.
"""

import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before importing shopping so the module-level imports
# don't fail in CI / test environments.
sys.modules.setdefault('agents', MagicMock())
sys.modules.setdefault('agents.mcp_agent', MagicMock())
sys.modules.setdefault('pantry', MagicMock())

from shopping import _auto_suggest_quantity  # noqa: E402


# ---------------------------------------------------------------------------
# Metric units — existing behaviour must not regress
# ---------------------------------------------------------------------------

class TestMetricUnits:
    def test_metric_weight_exact_multiple(self):
        # 500g needed, 250g pack → exactly 2 packs
        assert _auto_suggest_quantity("500g", "250g") == 2

    def test_metric_weight_rounds_up(self):
        # 700g needed, 250g pack → ceil(700/250)=3 (floor=2 → 2*250=500 < 700*0.85=595)
        assert _auto_suggest_quantity("700g", "250g") == 3

    def test_metric_weight_floor_covers(self):
        # 490g needed, 250g pack → floor=1 → 1*250=250 < 490*0.85=416.5 → ceil=2
        assert _auto_suggest_quantity("490g", "250g") == 2

    def test_metric_volume_ml(self):
        # 1000ml needed, 500ml pack → 2 packs
        assert _auto_suggest_quantity("1000ml", "500ml") == 2

    def test_metric_volume_liter_to_ml(self):
        # 1l needed, 500ml pack → 1l=1000ml, 1000/500=2
        assert _auto_suggest_quantity("1l", "500ml") == 2

    def test_metric_kg_to_g(self):
        # 1kg needed, 250g pack → 1000/250=4
        assert _auto_suggest_quantity("1kg", "250g") == 4

    def test_incompatible_units_fallback(self):
        # Weight vs volume → can't compare → fallback 1
        assert _auto_suggest_quantity("500g", "500ml") == 1


# ---------------------------------------------------------------------------
# Imperial weight units
# ---------------------------------------------------------------------------

class TestImperialWeight:
    def test_pounds_to_kg_pack(self):
        # 5 pounds = 5 * 453.592 = 2267.96g, 1kg pack = 1000g
        # ceil(2267.96 / 1000) = 3 (floor=2 → 2*1000=2000 < 2267.96*0.85=1927.8 → floor covers!)
        # Actually: floor=2 → 2000 >= 1927.8 → True → return floor = 2
        result = _auto_suggest_quantity("5 pounds", "1 kg")
        needed = 5 * 453.592  # 2267.96
        pack = 1000
        import math
        n_floor = max(1, math.floor(needed / pack))  # floor(2.268) = 2
        expected = n_floor if n_floor * pack >= needed * 0.85 else math.ceil(needed / pack)
        assert result == expected

    def test_pounds_explicit_value(self):
        # Independent check: 5 lb → 2267.96g, 1000g pack
        # floor = 2, 2*1000=2000, 2267.96*0.85=1927.8, 2000 >= 1927.8 → 2 packs
        assert _auto_suggest_quantity("5 pounds", "1 kg") == 2

    def test_lbs_abbreviation(self):
        # "5 lbs" same as "5 pounds"
        assert _auto_suggest_quantity("5 lbs", "1 kg") == 2

    def test_lb_abbreviation(self):
        assert _auto_suggest_quantity("5 lb", "1 kg") == 2

    def test_ounces_to_grams_pack(self):
        # 8 oz = 8 * 28.3495 = 226.796g, 250g pack
        # floor(226.796/250) = 0, max(1,0)=1
        # 1*250=250, 226.796*0.85=192.8 → 250 >= 192.8 → 1 pack
        assert _auto_suggest_quantity("8 ounces", "250g") == 1

    def test_oz_abbreviation(self):
        assert _auto_suggest_quantity("8 oz", "250g") == 1

    def test_ounce_singular(self):
        assert _auto_suggest_quantity("8 ounce", "250g") == 1

    def test_large_ounces_multiple_packs(self):
        # 32 oz = 907.18g, 250g pack
        # floor(907.18/250) = 3, 3*250=750, 907.18*0.85=771.1 → 750 < 771.1 → ceil = 4
        assert _auto_suggest_quantity("32 oz", "250g") == 4


# ---------------------------------------------------------------------------
# Imperial volume units
# ---------------------------------------------------------------------------

class TestImperialVolume:
    def test_cups_to_ml_pack(self):
        # 2 cups = 480ml, 500ml pack
        # floor(480/500) = 0, max(1,0) = 1
        # 1*500=500, 480*0.85=408 → 500 >= 408 → 1 pack
        assert _auto_suggest_quantity("2 cups", "500ml") == 1

    def test_cup_singular(self):
        # 1 cup = 240ml, 200ml pack
        # floor(240/200) = 1, 1*200=200, 240*0.85=204 → 200 < 204 → ceil=2
        assert _auto_suggest_quantity("1 cup", "200ml") == 2

    def test_tablespoons_to_ml(self):
        # 3 tablespoons = 45ml, 100ml pack
        # floor(45/100)=0, max(1,0)=1 → 1*100=100 >= 45*0.85=38.25 → 1 pack
        assert _auto_suggest_quantity("3 tablespoons", "100ml") == 1

    def test_tbsp_abbreviation(self):
        assert _auto_suggest_quantity("3 tbsp", "100ml") == 1

    def test_teaspoons_to_ml(self):
        # 6 teaspoons = 30ml, 100ml pack → 1 pack
        assert _auto_suggest_quantity("6 teaspoons", "100ml") == 1

    def test_tsp_abbreviation(self):
        assert _auto_suggest_quantity("6 tsp", "100ml") == 1

    def test_pints_to_ml(self):
        # 2 pints = 946.352ml, 500ml pack
        # floor(946.352/500)=1, 1*500=500, 946.352*0.85=804.4 → 500 < 804.4 → ceil=2
        assert _auto_suggest_quantity("2 pints", "500ml") == 2

    def test_quarts_to_ml(self):
        # 1 quart = 946.353ml, 1000ml pack
        # floor(946.353/1000)=0, max(1,0)=1 → 1*1000=1000 >= 946.353*0.85=804.4 → 1 pack
        assert _auto_suggest_quantity("1 quart", "1000ml") == 1


# ---------------------------------------------------------------------------
# Mixed / consolidated ingredient strings
# ---------------------------------------------------------------------------

class TestMixedIngredients:
    def test_metric_sum(self):
        # "200g + 595g" → 795g, 500g pack
        # floor(795/500)=1, 1*500=500, 795*0.85=675.75 → 500 < 675.75 → ceil=2
        assert _auto_suggest_quantity("200g + 595g", "500g") == 2

    def test_imperial_sum_cups_and_ml(self):
        # "1 cup + 200ml" → both parsed as volume: 240 + 200 = 440ml, 500ml pack
        # floor(440/500)=0, max(1,0)=1 → 1*500=500 >= 440*0.85=374 → 1 pack
        assert _auto_suggest_quantity("1 cup + 200ml", "500ml") == 1

    def test_parenthetical_gram(self):
        # "1 (795-gram) can" should parse 795g
        assert _auto_suggest_quantity("1 (795-gram) can", "400g") == 2


# ---------------------------------------------------------------------------
# Fallback / edge cases
# ---------------------------------------------------------------------------

class TestFallback:
    def test_unparseable_unit(self):
        # "3 cloves" has no known unit → fallback 1
        assert _auto_suggest_quantity("3 cloves", "100g") == 1

    def test_empty_ingredient(self):
        assert _auto_suggest_quantity("", "250g") == 1

    def test_empty_package(self):
        assert _auto_suggest_quantity("500g", "") == 1

    def test_both_empty(self):
        assert _auto_suggest_quantity("", "") == 1

    def test_no_number_in_ingredient(self):
        # "handful" has no number → fallback 1
        assert _auto_suggest_quantity("handful", "100g") == 1

    def test_zero_pack_size_fallback(self):
        # pack size of 0 would cause division-by-zero — should fall back gracefully
        # parse_total returns (0.0, 'weight') but pkg[0] == 0 so condition fails → 1
        assert _auto_suggest_quantity("500g", "0g") == 1

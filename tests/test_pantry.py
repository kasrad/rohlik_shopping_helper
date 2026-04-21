"""Tests for pantry.py — filter_pantry_items and apply_search_preferences."""

import pytest

from pantry import apply_search_preferences, filter_pantry_items


# ---------------------------------------------------------------------------
# filter_pantry_items
# ---------------------------------------------------------------------------


class TestFilterPantryItems:
    def test_no_pantry_file_returns_all_needed(self, tmp_path):
        ings = [{"name": "eggs", "quantity": "2"}]
        needed, matched = filter_pantry_items(ings, pantry_path=tmp_path / "pantry.md")
        assert needed == ings
        assert matched == []

    def test_ingredient_in_pantry_goes_to_matched(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- salt\n- pepper\n")
        ings = [{"name": "salt", "quantity": "1 tsp"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == []
        assert len(matched) == 1
        assert matched[0]["matched_pantry_item"] == "salt"

    def test_ingredient_not_in_pantry_goes_to_needed(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- salt\n")
        ings = [{"name": "butter", "quantity": "100g"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == ings
        assert matched == []

    def test_word_boundary_partial_name_match(self, tmp_path):
        # "salt" in pantry should match "kosher salt" in ingredient name
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- salt\n")
        ings = [{"name": "kosher salt", "quantity": "1 tsp"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == []
        assert matched[0]["matched_pantry_item"] == "salt"

    def test_word_boundary_no_false_match(self, tmp_path):
        # "salt" should NOT match "saltwater" — word boundary must be respected
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- salt\n")
        ings = [{"name": "saltwater fish", "quantity": "500g"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == ings
        assert matched == []

    def test_case_insensitive_match(self, tmp_path):
        # Pantry stored as "Butter" should still match ingredient "butter"
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- Butter\n")
        ings = [{"name": "butter", "quantity": "50g"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == []
        assert len(matched) == 1

    def test_mixed_needed_and_matched(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- eggs\n- flour\n")
        ings = [
            {"name": "eggs", "quantity": "2"},
            {"name": "sugar", "quantity": "100g"},
            {"name": "flour", "quantity": "200g"},
            {"name": "butter", "quantity": "50g"},
        ]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        needed_names = {i["name"] for i in needed}
        matched_names = {m["ingredient"]["name"] for m in matched}
        assert needed_names == {"sugar", "butter"}
        assert matched_names == {"eggs", "flour"}

    def test_empty_pantry_file_no_dash_lines_returns_all_needed(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("# Pantry\n\nSome notes without dash items\n")
        ings = [{"name": "eggs", "quantity": "2"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == ings
        assert matched == []

    def test_empty_ingredients_list_returns_empty_lists(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- salt\n")
        needed, matched = filter_pantry_items([], pantry_path=pantry)
        assert needed == []
        assert matched == []

    def test_matched_entry_contains_full_ingredient_dict(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- olive oil\n")
        ing = {"name": "olive oil", "quantity": "2 tbsp"}
        needed, matched = filter_pantry_items([ing], pantry_path=pantry)
        assert matched[0]["ingredient"] == ing

    def test_pantry_item_with_extra_whitespace_still_matches(self, tmp_path):
        pantry = tmp_path / "pantry.md"
        pantry.write_text("-  olive oil  \n")
        ings = [{"name": "olive oil", "quantity": "2 tbsp"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == []

    def test_stops_at_first_pantry_match(self, tmp_path):
        # When multiple pantry items could match, the first match wins
        pantry = tmp_path / "pantry.md"
        pantry.write_text("- oil\n- olive oil\n")
        ings = [{"name": "olive oil", "quantity": "2 tbsp"}]
        needed, matched = filter_pantry_items(ings, pantry_path=pantry)
        assert needed == []
        assert len(matched) == 1


# ---------------------------------------------------------------------------
# apply_search_preferences
# ---------------------------------------------------------------------------


class TestApplySearchPreferences:
    def test_no_prefs_file_returns_original(self, tmp_path):
        result = apply_search_preferences("garlic cloves", preferences_path=tmp_path / "prefs.md")
        assert result == "garlic cloves"

    def test_matching_rule_returns_replacement(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text("When you see 'garlic cloves', search 'garlic'\n")
        result = apply_search_preferences("garlic cloves", preferences_path=prefs)
        assert result == "garlic"

    def test_no_matching_rule_returns_original(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text("When you see 'garlic cloves', search 'garlic'\n")
        result = apply_search_preferences("butter", preferences_path=prefs)
        assert result == "butter"

    def test_case_insensitive_input_matches_rule(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text("When you see 'garlic cloves', search 'garlic'\n")
        result = apply_search_preferences("Garlic Cloves", preferences_path=prefs)
        assert result == "garlic"

    def test_look_for_variant_in_rule_works(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text('When you see "spring onion", look for "green onion"\n')
        result = apply_search_preferences("spring onion", preferences_path=prefs)
        assert result == "green onion"

    def test_second_rule_matches_when_first_does_not(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text(
            "When you see 'garlic cloves', search 'garlic'\n"
            "When you see 'heavy cream', search 'smetana'\n"
        )
        result = apply_search_preferences("heavy cream", preferences_path=prefs)
        assert result == "smetana"

    def test_empty_prefs_file_returns_original(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text("")
        result = apply_search_preferences("butter", preferences_path=prefs)
        assert result == "butter"

    def test_whitespace_around_input_still_matches(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text("When you see 'garlic cloves', search 'garlic'\n")
        result = apply_search_preferences("  garlic cloves  ", preferences_path=prefs)
        assert result == "garlic"

    def test_double_quotes_in_rule_parsed_correctly(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text('When you see "double butter", search "maslo"\n')
        result = apply_search_preferences("double butter", preferences_path=prefs)
        assert result == "maslo"

    def test_non_matching_lines_ignored(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text(
            "# This is a comment\n"
            "Some random note\n"
            "When you see 'garlic cloves', search 'garlic'\n"
        )
        result = apply_search_preferences("garlic cloves", preferences_path=prefs)
        assert result == "garlic"

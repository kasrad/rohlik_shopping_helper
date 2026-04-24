"""
End-to-end tests for app.py using Streamlit's AppTest harness.

These tests drive the real Streamlit script the way a user would: we seed
session_state to reach specific points in the flow (post-extraction,
post-fetch, etc.), then assert on rendered widgets and state transitions.

The RohlikMCPAgent is patched whenever the user's action would otherwise
trigger a network call (product search, add-to-basket).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest


APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
DEFAULT_TIMEOUT = 30


def _seeded_app(**state):
    """Return an AppTest with the given session_state pre-seeded."""
    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT)
    for k, v in state.items():
        at.session_state[k] = v
    return at


def _post_extraction_state(
    base_needed=None,
    matched=None,
    pantry_overrides=None,
    shopping_list=None,
    selections=None,
    quantities=None,
):
    """Shape of session state the app expects after PDFs have been processed."""
    return dict(
        base_needed=base_needed if base_needed is not None else [],
        matched=matched if matched is not None else [],
        pantry_overrides=pantry_overrides if pantry_overrides is not None else {},
        shopping_list=shopping_list,
        selections=selections if selections is not None else {},
        quantities=quantities if quantities is not None else {},
        extraction_summary="Processed recipes.",
    )


# ---------------------------------------------------------------------------
# Initial landing page
# ---------------------------------------------------------------------------


class TestInitialLoad:
    def test_title_renders(self):
        at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
        assert not at.exception
        assert any("Rohlik Shopping Agent" in t.value for t in at.title)

    def test_upload_prompt_shown_when_no_files(self):
        at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
        info_texts = [i.value for i in at.info]
        assert any("upload at least one recipe file" in txt.lower() for txt in info_texts)

    def test_no_tabs_before_extraction(self):
        # Tabs only appear once session state indicates recipes were processed.
        at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
        assert len(at.tabs) == 0

    def test_no_start_over_button_before_extraction(self):
        at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
        assert not any(b.label == "↩ Start Over" for b in at.button)


# ---------------------------------------------------------------------------
# Post-extraction — the three tabs appear
# ---------------------------------------------------------------------------


class TestPostExtraction:
    def test_all_three_tabs_appear(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
        )
        at = _seeded_app(**state).run()
        assert not at.exception
        tab_labels = [t.label for t in at.tabs]
        assert "📋 Pantry Match" in tab_labels
        assert "🔍 Rohlik Search" in tab_labels
        assert "🛒 Cart Summary" in tab_labels

    def test_extraction_summary_is_displayed(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
        )
        state["extraction_summary"] = "Successfully processed 2 recipes!"
        at = _seeded_app(**state).run()
        assert any("Successfully processed 2 recipes" in i.value for i in at.info)

    def test_start_over_button_appears_and_clears_state(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            matched=[{"ingredient": {"name": "salt", "quantity": "1 tsp"}, "matched_pantry_item": "salt"}],
            pantry_overrides={"salt": True},
        )
        at = _seeded_app(**state).run()

        start_over = next(b for b in at.button if b.label == "↩ Start Over")
        start_over.click().run()

        # Flow-state keys that gate the tab view should be fully removed.
        for key in ["base_needed", "matched", "pantry_overrides", "shopping_list",
                    "selections", "effective_needed"]:
            assert key not in at.session_state, f"{key} should have been cleared"
        # The top-of-script initializer resets these to their defaults.
        assert at.session_state["extraction_summary"] is None
        assert at.session_state["quantities"] == {}
        # Tabs should no longer render since gating keys are gone.
        assert len(at.tabs) == 0


# ---------------------------------------------------------------------------
# Pantry Match tab
# ---------------------------------------------------------------------------


class TestPantryMatchTab:
    def test_matched_items_render_as_checkboxes(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            matched=[
                {"ingredient": {"name": "salt", "quantity": "1 tsp"}, "matched_pantry_item": "salt"},
                {"ingredient": {"name": "pepper", "quantity": "1 tsp"}, "matched_pantry_item": "pepper"},
            ],
        )
        at = _seeded_app(**state).run()
        labels = [c.label for c in at.checkbox]
        assert any("salt" in lbl and "1 tsp" in lbl for lbl in labels)
        assert any("pepper" in lbl for lbl in labels)

    def test_no_match_shows_info_message(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            matched=[],
        )
        at = _seeded_app(**state).run()
        info_texts = [i.value for i in at.info]
        assert any("No items matched your pantry" in txt for txt in info_texts)

    def test_unchecking_pantry_moves_item_to_effective_needed(self):
        # Matched items default to "have it" (True). Unchecking should add the
        # ingredient to effective_needed on the next run.
        state = _post_extraction_state(
            base_needed=[],
            matched=[{"ingredient": {"name": "salt", "quantity": "1 tsp"}, "matched_pantry_item": "salt"}],
        )
        at = _seeded_app(**state).run()

        cb = next(c for c in at.checkbox if "salt" in c.label)
        assert cb.value is True
        cb.uncheck().run()

        assert at.session_state["pantry_overrides"]["salt"] is False
        effective = at.session_state["effective_needed"]
        assert any(ing["name"] == "salt" for ing in effective)


# ---------------------------------------------------------------------------
# Rohlik Search tab
# ---------------------------------------------------------------------------


class TestRohlikSearchTab:
    def test_all_items_in_pantry_shows_success(self):
        # When there's nothing to buy, the tab should congratulate the user.
        state = _post_extraction_state(
            base_needed=[],
            matched=[{"ingredient": {"name": "salt", "quantity": "1 tsp"}, "matched_pantry_item": "salt"}],
            pantry_overrides={"salt": True},
        )
        at = _seeded_app(**state).run()
        success_texts = [s.value for s in at.success]
        assert any("All ingredients are covered by your pantry" in txt for txt in success_texts)

    def test_find_products_button_visible_when_needed(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
        )
        at = _seeded_app(**state).run()
        assert any(b.label == "Find Products on Rohlik.cz" for b in at.button)

    def test_shopping_list_renders_product_radios(self):
        shopping_list = [
            {
                "ingredient": "butter",
                "search_term": "máslo",
                "quantity_needed": "100g",
                "options": [
                    {"name": "Brand A Butter", "product_id": 111,
                     "package_size": "250g", "price": 49.9, "price_per_unit": "199.60 Kč/kg"},
                    {"name": "Brand B Butter", "product_id": 222,
                     "package_size": "200g", "price": 39.9, "price_per_unit": "199.50 Kč/kg"},
                ],
            },
        ]
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            shopping_list=shopping_list,
        )
        at = _seeded_app(**state).run()
        assert not at.exception
        # One radio per ingredient with options
        assert len(at.radio) == 1
        radio_options = at.radio[0].options
        assert any("Brand A Butter" in opt for opt in radio_options)
        assert any("Brand B Butter" in opt for opt in radio_options)
        # And the skip sentinel should always be present
        assert any("Don't add anything" in opt for opt in radio_options)

    def test_refetch_all_products_button_clears_shopping_list(self):
        shopping_list = [
            {
                "ingredient": "butter",
                "search_term": "máslo",
                "quantity_needed": "100g",
                "options": [{"name": "X", "product_id": 1, "package_size": "250g", "price": 10.0, "price_per_unit": "40 Kč/kg"}],
            },
        ]
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            shopping_list=shopping_list,
            selections={"butter": 0},
            quantities={"butter": 1},
        )
        at = _seeded_app(**state).run()
        refetch = next(b for b in at.button if b.label == "Refetch All Products")
        refetch.click().run()
        assert at.session_state["shopping_list"] is None
        assert at.session_state["quantities"] == {}

    def test_ingredient_with_no_results_shows_warning_and_refetch(self):
        shopping_list = [
            {
                "ingredient": "exotic-spice",
                "search_term": "exotic-spice",
                "quantity_needed": "1",
                "options": [],
            },
        ]
        state = _post_extraction_state(
            base_needed=[{"name": "exotic-spice", "quantity": "1"}],
            shopping_list=shopping_list,
        )
        at = _seeded_app(**state).run()
        warning_texts = [w.value for w in at.warning]
        assert any("No alternatives found" in w for w in warning_texts)
        # Per-item refetch button is present with the ingredient name in the label
        assert any("exotic-spice" in b.label and "Refetch" in b.label for b in at.button)


# ---------------------------------------------------------------------------
# Cart Summary tab — selection -> cart math
# ---------------------------------------------------------------------------


class TestCartSummaryTab:
    def _build_shopping_list(self):
        return [
            {
                "ingredient": "butter",
                "search_term": "máslo",
                "quantity_needed": "100g",
                "options": [
                    {"name": "Brand A Butter", "product_id": 111,
                     "package_size": "250g", "price": 49.9, "price_per_unit": "199.60 Kč/kg"},
                    {"name": "Brand B Butter", "product_id": 222,
                     "package_size": "200g", "price": 39.9, "price_per_unit": "199.50 Kč/kg"},
                ],
            },
            {
                "ingredient": "eggs",
                "search_term": "vejce",
                "quantity_needed": "4 pcs",
                "options": [
                    {"name": "Free-Range Eggs 10pk", "product_id": 333,
                     "package_size": "10 ks", "price": 89.0, "price_per_unit": "8.90 Kč/ks"},
                ],
            },
        ]

    def test_cart_summary_requires_shopping_list(self):
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            shopping_list=None,
        )
        at = _seeded_app(**state).run()
        info_texts = [i.value for i in at.info]
        assert any("Fetch products in the" in txt for txt in info_texts)

    def test_skipped_item_shown_when_selection_is_minus_one(self):
        shopping = self._build_shopping_list()
        state = _post_extraction_state(
            base_needed=[
                {"name": "butter", "quantity": "100g"},
                {"name": "eggs", "quantity": "4 pcs"},
            ],
            shopping_list=shopping,
            selections={"butter": -1, "eggs": 0},
            quantities={"butter": 1, "eggs": 1},
        )
        at = _seeded_app(**state).run()
        # The "Add to basket" button is rendered on the cart summary tab.
        assert any(b.label == "🛒 Add to basket" for b in at.button)
        # Estimated total should reflect only the selected eggs item: 89.0 * 1
        md_texts = "\n".join(m.value for m in at.markdown)
        assert "89.00 Kč" in md_texts

    def test_estimated_total_sums_selected_options(self):
        shopping = self._build_shopping_list()
        state = _post_extraction_state(
            base_needed=[
                {"name": "butter", "quantity": "100g"},
                {"name": "eggs", "quantity": "4 pcs"},
            ],
            shopping_list=shopping,
            selections={"butter": 0, "eggs": 0},  # Brand A Butter + Eggs
            quantities={"butter": 2, "eggs": 1},  # 2 packs butter, 1 pack eggs
        )
        at = _seeded_app(**state).run()
        md_texts = "\n".join(m.value for m in at.markdown)
        # 49.9 * 2 + 89.0 * 1 = 188.80 Kč
        assert "188.80 Kč" in md_texts

    def test_pantry_override_items_appear_in_skipped(self):
        # Items kept in pantry (override True) should be listed in the "Skipped"
        # table on the cart summary tab.
        shopping = [{
            "ingredient": "butter",
            "search_term": "máslo",
            "quantity_needed": "100g",
            "options": [{"name": "Brand A", "product_id": 111, "package_size": "250g",
                         "price": 49.9, "price_per_unit": "199.60 Kč/kg"}],
        }]
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            matched=[{"ingredient": {"name": "salt", "quantity": "1 tsp"}, "matched_pantry_item": "salt"}],
            pantry_overrides={"salt": True},
            shopping_list=shopping,
            selections={"butter": 0},
            quantities={"butter": 1},
        )
        at = _seeded_app(**state).run()
        # The skipped dataframe/table should contain the pantry item.
        # We check by scanning the rendered markdown + dataframes for 'salt'.
        table_text = ""
        for df in at.dataframe:
            table_text += str(df.value)
        for tbl in at.table:
            table_text += str(tbl.value)
        assert "salt" in table_text.lower()
        assert "pantry" in table_text.lower()


# ---------------------------------------------------------------------------
# Add to basket — agent is patched so no real MCP call happens
# ---------------------------------------------------------------------------


class TestAddToBasket:
    def test_add_to_basket_invokes_agent_with_mapped_items(self, tmp_path, monkeypatch):
        # Redirect the final_selections.json write into a temp dir so the test
        # doesn't pollute the repo.
        import config
        monkeypatch.setattr(config, "ROOT", tmp_path)

        shopping = [{
            "ingredient": "butter",
            "search_term": "máslo",
            "quantity_needed": "100g",
            "options": [
                {"name": "Brand A Butter", "product_id": 111,
                 "package_size": "250g", "price": 49.9, "price_per_unit": "199.60 Kč/kg"},
            ],
        }]
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            shopping_list=shopping,
            selections={"butter": 0},
            quantities={"butter": 3},
        )

        fake_agent = MagicMock()
        fake_agent.add_items_to_basket.return_value = "OK: 1 item added"

        with patch("agents.mcp_agent.RohlikMCPAgent", return_value=fake_agent):
            at = _seeded_app(**state).run()
            add_btn = next(b for b in at.button if b.label == "🛒 Add to basket")
            add_btn.click().run()

        assert fake_agent.add_items_to_basket.called
        call_args = fake_agent.add_items_to_basket.call_args[0][0]
        assert call_args == [{"productId": 111, "quantity": 3}]

        success_texts = [s.value for s in at.success]
        assert any("Successfully added" in txt for txt in success_texts)

    def test_add_to_basket_with_no_selections_shows_warning(self):
        # All items marked skip -> no cart items -> warning, no agent call.
        shopping = [{
            "ingredient": "butter",
            "search_term": "máslo",
            "quantity_needed": "100g",
            "options": [{"name": "Brand A", "product_id": 111, "package_size": "250g",
                         "price": 49.9, "price_per_unit": "199.60 Kč/kg"}],
        }]
        state = _post_extraction_state(
            base_needed=[{"name": "butter", "quantity": "100g"}],
            shopping_list=shopping,
            selections={"butter": -1},
            quantities={"butter": 1},
        )

        fake_agent = MagicMock()
        with patch("agents.mcp_agent.RohlikMCPAgent", return_value=fake_agent):
            at = _seeded_app(**state).run()
            add_btn = next(b for b in at.button if b.label == "🛒 Add to basket")
            add_btn.click().run()

        assert not fake_agent.add_items_to_basket.called
        warning_texts = [w.value for w in at.warning]
        assert any("No items selected" in w for w in warning_texts)

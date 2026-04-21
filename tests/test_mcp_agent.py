"""Tests for agents/mcp_agent.py — RohlikMCPAgent with mocked _run and Anthropic."""

import json
import pytest
from unittest.mock import MagicMock, patch

from agents.mcp_agent import RohlikMCPAgent


SAMPLE_PRODUCTS = [
    {
        "name": "Hollandia Máslo",
        "product_id": 1234567,
        "package_size": "250g",
        "price": 59.90,
        "price_per_unit": "239.60 Kč/kg",
        "image_url": "https://example.com/img.jpg",
    },
    {
        "name": "Madeta Máslo",
        "product_id": 7654321,
        "package_size": "250g",
        "price": 54.90,
        "price_per_unit": "219.60 Kč/kg",
        "image_url": "",
    },
    {
        "name": "Président Máslo",
        "product_id": 9999999,
        "package_size": "200g",
        "price": 62.00,
        "price_per_unit": "310.00 Kč/kg",
        "image_url": "",
    },
]

BATCH_RESULT = {
    "butter": SAMPLE_PRODUCTS[:2],
    "eggs": [
        {
            "name": "Vejce M",
            "product_id": 111,
            "package_size": "10 ks",
            "price": 55.0,
            "price_per_unit": "5.50 Kč/ks",
            "image_url": "",
        }
    ],
}

CART_ITEMS = [{"productId": 1234567, "quantity": 2}, {"productId": 9999999, "quantity": 1}]


@pytest.fixture
def agent(tmp_path):
    """RohlikMCPAgent with mocked Anthropic client and no real env files."""
    with patch("agents.mcp_agent.anthropic.Anthropic"):
        inst = RohlikMCPAgent(prefs_path=tmp_path / "prefs.md")
    return inst


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestAgentConstruction:
    def test_constructs_without_preferences_file(self, tmp_path):
        with patch("agents.mcp_agent.anthropic.Anthropic"):
            inst = RohlikMCPAgent(prefs_path=tmp_path / "missing.md")
        assert inst.instruction  # non-empty system prompt

    def test_loads_preferences_content_into_instruction(self, tmp_path):
        prefs = tmp_path / "prefs.md"
        prefs.write_text("When you see 'garlic cloves', search 'garlic'\n")
        with patch("agents.mcp_agent.anthropic.Anthropic"):
            inst = RohlikMCPAgent(prefs_path=prefs)
        assert "garlic" in inst.instruction

    def test_default_model_is_haiku(self, tmp_path):
        with patch("agents.mcp_agent.anthropic.Anthropic"):
            inst = RohlikMCPAgent(prefs_path=tmp_path / "missing.md")
        assert "haiku" in inst.model

    def test_custom_model_stored(self, tmp_path):
        with patch("agents.mcp_agent.anthropic.Anthropic"):
            inst = RohlikMCPAgent(model="claude-sonnet-4-6", prefs_path=tmp_path / "missing.md")
        assert inst.model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# find_alternatives
# ---------------------------------------------------------------------------


class TestFindAlternatives:
    def test_clean_json_array_parsed(self, agent):
        agent._run = MagicMock(return_value=json.dumps(SAMPLE_PRODUCTS))
        result = agent.find_alternatives("máslo")
        assert result == SAMPLE_PRODUCTS

    def test_json_in_json_markdown_fence_stripped(self, agent):
        fenced = f"```json\n{json.dumps(SAMPLE_PRODUCTS)}\n```"
        agent._run = MagicMock(return_value=fenced)
        result = agent.find_alternatives("máslo")
        assert result == SAMPLE_PRODUCTS

    def test_json_in_plain_markdown_fence_stripped(self, agent):
        fenced = f"```\n{json.dumps(SAMPLE_PRODUCTS)}\n```"
        agent._run = MagicMock(return_value=fenced)
        result = agent.find_alternatives("máslo")
        assert result == SAMPLE_PRODUCTS

    def test_run_exception_returns_empty_list(self, agent):
        agent._run = MagicMock(side_effect=Exception("MCP connection failed"))
        result = agent.find_alternatives("máslo")
        assert result == []

    def test_unparseable_response_returns_empty_list(self, agent):
        agent._run = MagicMock(return_value="Sorry, I could not find any products.")
        result = agent.find_alternatives("máslo")
        assert result == []

    def test_empty_json_array_returned_as_is(self, agent):
        agent._run = MagicMock(return_value="[]")
        result = agent.find_alternatives("máslo")
        assert result == []

    def test_ingredient_name_included_in_prompt(self, agent):
        agent._run = MagicMock(return_value="[]")
        agent.find_alternatives("cherry tomatoes")
        prompt = agent._run.call_args[0][0]
        assert "cherry tomatoes" in prompt

    def test_returns_list_type(self, agent):
        agent._run = MagicMock(return_value=json.dumps(SAMPLE_PRODUCTS))
        result = agent.find_alternatives("máslo")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# find_alternatives_batch
# ---------------------------------------------------------------------------


class TestFindAlternativesBatch:
    def test_empty_ingredients_returns_empty_dict_without_calling_run(self, agent):
        agent._run = MagicMock()
        result = agent.find_alternatives_batch([])
        assert result == {}
        agent._run.assert_not_called()

    def test_clean_json_object_parsed(self, agent):
        agent._run = MagicMock(return_value=json.dumps(BATCH_RESULT))
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert result == BATCH_RESULT

    def test_json_in_markdown_fence_stripped(self, agent):
        fenced = f"```json\n{json.dumps(BATCH_RESULT)}\n```"
        agent._run = MagicMock(return_value=fenced)
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert result["butter"] == BATCH_RESULT["butter"]
        assert result["eggs"] == BATCH_RESULT["eggs"]

    def test_prose_before_json_uses_regex_fallback(self, agent):
        prose = f"Here are the results:\n{json.dumps(BATCH_RESULT)}\nHope this helps!"
        agent._run = MagicMock(return_value=prose)
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert result["butter"] == BATCH_RESULT["butter"]

    def test_missing_ingredient_filled_with_empty_list(self, agent):
        partial = {"butter": SAMPLE_PRODUCTS[:1]}
        agent._run = MagicMock(return_value=json.dumps(partial))
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert result["butter"] == partial["butter"]
        assert result["eggs"] == []

    def test_missing_ingredient_warning_printed(self, agent, capsys):
        partial = {"butter": SAMPLE_PRODUCTS[:1]}
        agent._run = MagicMock(return_value=json.dumps(partial))
        agent.find_alternatives_batch(["butter", "eggs"])
        captured = capsys.readouterr()
        assert "eggs" in captured.out

    def test_run_exception_returns_all_empty_dict(self, agent):
        agent._run = MagicMock(side_effect=Exception("connection error"))
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert result == {"butter": [], "eggs": []}

    def test_unparseable_response_returns_all_empty_dict(self, agent):
        agent._run = MagicMock(return_value="I cannot find those products.")
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert result == {"butter": [], "eggs": []}

    def test_all_ingredients_keys_present_in_result(self, agent):
        agent._run = MagicMock(return_value=json.dumps(BATCH_RESULT))
        result = agent.find_alternatives_batch(["butter", "eggs"])
        assert "butter" in result
        assert "eggs" in result

    def test_max_tokens_16000_passed_to_run(self, agent):
        agent._run = MagicMock(return_value=json.dumps(BATCH_RESULT))
        agent.find_alternatives_batch(["butter", "eggs"])
        _, kwargs = agent._run.call_args
        assert kwargs["max_tokens"] == 16000

    def test_single_ingredient_works(self, agent):
        single = {"butter": SAMPLE_PRODUCTS}
        agent._run = MagicMock(return_value=json.dumps(single))
        result = agent.find_alternatives_batch(["butter"])
        assert result["butter"] == SAMPLE_PRODUCTS

    def test_ingredient_names_included_in_prompt(self, agent):
        agent._run = MagicMock(return_value=json.dumps(BATCH_RESULT))
        agent.find_alternatives_batch(["butter", "eggs"])
        prompt = agent._run.call_args[0][0]
        assert "butter" in prompt
        assert "eggs" in prompt


# ---------------------------------------------------------------------------
# add_items_to_basket
# ---------------------------------------------------------------------------


class TestAddItemsToBasket:
    def test_success_returns_agent_response_string(self, agent):
        agent._run = MagicMock(return_value="Items added successfully!")
        result = agent.add_items_to_basket(CART_ITEMS)
        assert result == "Items added successfully!"

    def test_run_exception_returns_error_message_string(self, agent):
        agent._run = MagicMock(side_effect=Exception("MCP timeout"))
        result = agent.add_items_to_basket(CART_ITEMS)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_product_ids_appear_in_prompt(self, agent):
        agent._run = MagicMock(return_value="ok")
        agent.add_items_to_basket(CART_ITEMS)
        prompt = agent._run.call_args[0][0]
        assert "1234567" in prompt
        assert "9999999" in prompt

    def test_empty_items_list_still_calls_run(self, agent):
        agent._run = MagicMock(return_value="ok")
        result = agent.add_items_to_basket([])
        assert result == "ok"
        agent._run.assert_called_once()

    def test_returns_string_type(self, agent):
        agent._run = MagicMock(return_value="Done")
        result = agent.add_items_to_basket(CART_ITEMS)
        assert isinstance(result, str)

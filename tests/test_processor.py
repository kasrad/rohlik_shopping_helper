"""Tests for processor.py — covers _find_first_json_array, extract_text_from_pdf,
extract_text_from_markdown, consolidate_ingredients, and parse_recipe_ingredients."""

import json
from unittest.mock import MagicMock, patch

import pytest

from processor import (
    _find_first_json_array,
    consolidate_ingredients,
    extract_text_from_markdown,
    extract_text_from_pdf,
    parse_recipe_ingredients,
)


# ---------------------------------------------------------------------------
# extract_text_from_pdf
# ---------------------------------------------------------------------------


class TestExtractTextFromPdf:
    def _make_reader(self, page_texts):
        pages = []
        for text in page_texts:
            page = MagicMock()
            page.extract_text.return_value = text
            pages.append(page)
        reader = MagicMock()
        reader.pages = pages
        return reader

    def test_single_page_text_returned(self):
        reader = self._make_reader(["Ingredients: 2 eggs"])
        with patch("processor.PdfReader", return_value=reader):
            result = extract_text_from_pdf("fake.pdf")
        assert "Ingredients: 2 eggs" in result

    def test_multiple_pages_concatenated(self):
        reader = self._make_reader(["Page 1 text", "Page 2 text"])
        with patch("processor.PdfReader", return_value=reader):
            result = extract_text_from_pdf("fake.pdf")
        assert "Page 1 text" in result
        assert "Page 2 text" in result

    def test_empty_pdf_returns_empty_string(self):
        reader = MagicMock()
        reader.pages = []
        with patch("processor.PdfReader", return_value=reader):
            result = extract_text_from_pdf("fake.pdf")
        assert result == ""

    def test_malformed_pdf_returns_empty_string(self):
        with patch("processor.PdfReader", side_effect=Exception("Malformed PDF")):
            result = extract_text_from_pdf("bad.pdf")
        assert result == ""

    def test_pages_separated_by_newline(self):
        reader = self._make_reader(["Page 1", "Page 2"])
        with patch("processor.PdfReader", return_value=reader):
            result = extract_text_from_pdf("fake.pdf")
        # Each page ends with "\n" per the implementation
        assert "Page 1\n" in result
        assert "Page 2\n" in result

    def test_accepts_file_like_object(self):
        import io
        buf = io.BytesIO(b"fake pdf bytes")
        reader = self._make_reader(["recipe text"])
        with patch("processor.PdfReader", return_value=reader) as mock_cls:
            extract_text_from_pdf(buf)
        mock_cls.assert_called_once_with(buf)


# ---------------------------------------------------------------------------
# _find_first_json_array
# ---------------------------------------------------------------------------


class TestFindFirstJsonArray:
    def test_simple_array(self):
        assert _find_first_json_array('[{"a":1}]') == '[{"a":1}]'

    def test_text_before_array(self):
        assert _find_first_json_array('Here: [{"a":1}]') == '[{"a":1}]'

    def test_two_separate_arrays_returns_first(self):
        assert _find_first_json_array('[1] and [2,3]') == '[1]'

    def test_nested_array(self):
        assert _find_first_json_array('[[1,2],[3,4]]') == '[[1,2],[3,4]]'

    def test_no_array_returns_none(self):
        assert _find_first_json_array('no array here') is None

    def test_empty_string_returns_none(self):
        assert _find_first_json_array('') is None

    def test_string_containing_brackets(self):
        # Brackets inside a JSON string value must not confuse the parser
        result = _find_first_json_array('[{"key": "val[ue]"}]')
        assert result == '[{"key": "val[ue]"}]'

    def test_escaped_backslash_in_string(self):
        # Ensure escape sequences inside strings are handled correctly
        result = _find_first_json_array('[{"k": "a\\\\b"}]')
        assert result == '[{"k": "a\\\\b"}]'

    def test_prose_after_first_array_ignored(self):
        text = 'Result: [{"name": "eggs", "quantity": "2"}] — done.'
        assert result == '[{"name": "eggs", "quantity": "2"}]' if (result := _find_first_json_array(text)) else False
        assert _find_first_json_array(text) == '[{"name": "eggs", "quantity": "2"}]'


# ---------------------------------------------------------------------------
# extract_text_from_markdown
# ---------------------------------------------------------------------------

NYT_FRONTMATTER = 'source: "https://cooking.nytimes.com/recipes/1234"\n'

NYT_WITH_INGREDIENTS = (
    NYT_FRONTMATTER
    + "# My Recipe\n\n"
    "## Ingredients\n"
    "- 2 eggs\n"
    "- 1 cup flour\n\n"
    "## Instructions\n"
    "Mix everything.\n"
)

NYT_WITHOUT_INGREDIENTS = (
    NYT_FRONTMATTER
    + "# My Recipe\n\n"
    "## Steps\n"
    "Mix everything.\n"
)

NON_NYT_MARKDOWN = (
    "source: https://example.com/recipe\n"
    "# My Recipe\n\n"
    "## Ingredients\n"
    "- butter\n\n"
    "## Instructions\n"
    "Cook it.\n"
)


class TestExtractTextFromMarkdown:
    def test_nyt_with_ingredients_section_returns_only_ingredients(self):
        result = extract_text_from_markdown(NYT_WITH_INGREDIENTS)
        assert "## Ingredients" in result
        assert "2 eggs" in result
        assert "## Instructions" not in result

    def test_nyt_without_ingredients_section_returns_full_content(self, capsys):
        result = extract_text_from_markdown(NYT_WITHOUT_INGREDIENTS)
        assert "## Steps" in result
        assert "Mix everything" in result

    def test_nyt_without_ingredients_prints_warning(self, capsys):
        extract_text_from_markdown(NYT_WITHOUT_INGREDIENTS)
        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "## Ingredients" in captured.out

    def test_non_nyt_markdown_returns_full_content(self):
        result = extract_text_from_markdown(NON_NYT_MARKDOWN)
        assert result == NON_NYT_MARKDOWN

    def test_bytes_input(self):
        result = extract_text_from_markdown(NYT_WITH_INGREDIENTS.encode("utf-8"))
        assert "## Ingredients" in result
        assert "## Instructions" not in result

    def test_string_input(self):
        result = extract_text_from_markdown(NYT_WITH_INGREDIENTS)
        assert isinstance(result, str)

    def test_file_like_object_bytes(self):
        import io
        buf = io.BytesIO(NYT_WITH_INGREDIENTS.encode("utf-8"))
        result = extract_text_from_markdown(buf)
        assert "## Ingredients" in result

    def test_file_like_object_string(self):
        import io
        buf = io.StringIO(NYT_WITH_INGREDIENTS)
        result = extract_text_from_markdown(buf)
        assert "## Ingredients" in result


# ---------------------------------------------------------------------------
# consolidate_ingredients
# ---------------------------------------------------------------------------


class TestConsolidateIngredients:
    def test_same_ingredient_quantities_concatenated(self):
        lists = [
            [{"name": "butter", "quantity": "100g"}],
            [{"name": "butter", "quantity": "50g"}],
        ]
        result = consolidate_ingredients(lists)
        assert len(result) == 1
        assert result[0]["name"] == "butter"
        assert "100g" in result[0]["quantity"]
        assert "50g" in result[0]["quantity"]

    def test_different_ingredients_both_preserved(self):
        lists = [
            [{"name": "eggs", "quantity": "2"}],
            [{"name": "flour", "quantity": "1 cup"}],
        ]
        result = consolidate_ingredients(lists)
        names = {r["name"] for r in result}
        assert "eggs" in names
        assert "flour" in names
        assert len(result) == 2

    def test_ingredient_with_no_name_is_skipped(self):
        lists = [
            [{"name": "", "quantity": "1 cup"}, {"name": "salt", "quantity": "1 tsp"}],
        ]
        result = consolidate_ingredients(lists)
        assert len(result) == 1
        assert result[0]["name"] == "salt"

    def test_ingredient_with_none_name_is_skipped(self):
        lists = [
            [{"name": None, "quantity": "1 cup"}, {"name": "pepper", "quantity": "1 tsp"}],
        ]
        result = consolidate_ingredients(lists)
        assert len(result) == 1
        assert result[0]["name"] == "pepper"

    def test_case_insensitive_merge_keeps_first_casing(self):
        lists = [
            [{"name": "Butter", "quantity": "100g"}],
            [{"name": "butter", "quantity": "50g"}],
        ]
        result = consolidate_ingredients(lists)
        assert len(result) == 1
        assert result[0]["name"] == "Butter"  # original casing preserved

    def test_empty_input(self):
        assert consolidate_ingredients([]) == []

    def test_empty_inner_lists(self):
        assert consolidate_ingredients([[], []]) == []


# ---------------------------------------------------------------------------
# parse_recipe_ingredients (mocked Claude)
# ---------------------------------------------------------------------------

INGREDIENTS = [{"name": "eggs", "quantity": "2"}, {"name": "flour", "quantity": "1 cup"}]


def _make_mock_client(text: str):
    """Return a mock anthropic.Anthropic client whose messages.create returns text."""
    mock_content = MagicMock()
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


class TestParseRecipeIngredients:
    def test_valid_json_response(self):
        mock_client = _make_mock_client(json.dumps(INGREDIENTS))
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            result = parse_recipe_ingredients("2 eggs, 1 cup flour", "fake-key")
        assert result == INGREDIENTS

    def test_response_with_json_markdown_fence(self):
        fenced = f"```json\n{json.dumps(INGREDIENTS)}\n```"
        mock_client = _make_mock_client(fenced)
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            result = parse_recipe_ingredients("2 eggs, 1 cup flour", "fake-key")
        assert result == INGREDIENTS

    def test_response_with_plain_markdown_fence(self):
        fenced = f"```\n{json.dumps(INGREDIENTS)}\n```"
        mock_client = _make_mock_client(fenced)
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            result = parse_recipe_ingredients("2 eggs, 1 cup flour", "fake-key")
        assert result == INGREDIENTS

    def test_response_with_prose_before_array_uses_fallback(self):
        prose_response = f"Here are the ingredients:\n{json.dumps(INGREDIENTS)}\nEnjoy!"
        mock_client = _make_mock_client(prose_response)
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            result = parse_recipe_ingredients("2 eggs, 1 cup flour", "fake-key")
        assert result == INGREDIENTS

    def test_empty_response_raises_runtime_error(self):
        mock_content = MagicMock()
        mock_content.text = ""
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            with pytest.raises(RuntimeError, match="empty response"):
                parse_recipe_ingredients("2 eggs", "fake-key")

    def test_no_content_raises_runtime_error(self):
        mock_response = MagicMock()
        mock_response.content = []
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            with pytest.raises(RuntimeError):
                parse_recipe_ingredients("2 eggs", "fake-key")

    def test_empty_recipe_text_raises_value_error(self):
        with pytest.raises(ValueError, match="No text"):
            parse_recipe_ingredients("   ", "fake-key")

    def test_api_failure_raises_runtime_error(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("network error")
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Claude API call failed"):
                parse_recipe_ingredients("2 eggs", "fake-key")

    def test_unparseable_response_raises_runtime_error(self):
        mock_client = _make_mock_client("This is just plain text with no JSON at all.")
        with patch("processor.anthropic.Anthropic", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Could not parse"):
                parse_recipe_ingredients("2 eggs", "fake-key")

import re
from pathlib import Path

from config import PANTRY_PATH, PREFERENCES_PATH


def filter_pantry_items(ingredients, pantry_path=PANTRY_PATH):
    """
    Filters out ingredients already present in the user's pantry manifest.

    Returns:
        tuple: (needed_ingredients, matched_ingredients_for_confirmation)
    """
    if not Path(pantry_path).exists():
        return ingredients, []

    with open(pantry_path, "r") as f:
        pantry_items = [
            line.strip("- ").lower().strip()
            for line in f
            if line.strip().startswith("-")
        ]

    needed = []
    matched = []
    for ing in ingredients:
        ing_name = ing['name'].lower().strip()
        match_found = False
        matched_item_name = ""

        for p_item in pantry_items:
            if not p_item:
                continue
            # Word boundaries: "salt" matches "kosher salt" but not "saltwater"
            if re.search(r'\b' + re.escape(p_item) + r'\b', ing_name):
                match_found = True
                matched_item_name = p_item
                break

        if not match_found:
            needed.append(ing)
        else:
            matched.append({"ingredient": ing, "matched_pantry_item": matched_item_name})

    return needed, matched


def apply_search_preferences(ingredient_name, preferences_path=PREFERENCES_PATH):
    """
    Checks user preferences for explicit search-rewrite rules.
    Example: "When you see 'garlic cloves', search 'garlic'"

    Returns the mapped search term, or the original name if no rule matches.
    """
    if not Path(preferences_path).exists():
        return ingredient_name

    ing_lower = ingredient_name.lower().strip()

    with open(preferences_path, "r") as f:
        for line in f:
            match = re.search(
                r"When you see ['\"](.+?)['\"], (?:search|look for) ['\"](.+?)['\"]",
                line,
                re.IGNORECASE,
            )
            if match:
                target = match.group(1).lower().strip()
                replacement = match.group(2).strip()
                if ing_lower == target:
                    return replacement

    return ingredient_name

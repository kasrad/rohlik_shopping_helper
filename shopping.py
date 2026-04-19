import math
import re
import time
import threading

from agents.mcp_agent import RohlikMCPAgent
from pantry import apply_search_preferences

# Prevents concurrent MCP agent initialisation from hitting rate limits
# or causing Node.js subprocess errors.
_init_lock = threading.Lock()


def _auto_suggest_quantity(ingredient_qty_str: str, package_size_str: str, product_name_str: str = "") -> int:
    """
    Estimate how many packs to buy using a 15% underage tolerance:
    - Try floor(needed / pack). If it covers ≥ 85% of what's needed, use it.
    - Otherwise use ceil (never leave more than 15% uncovered).

    Parses weight/volume from package_size_str, falling back to product_name_str.
    Sums all quantities in the ingredient string (e.g. "200g + 595g" → 795g).
    Handles long-form and hyphenated units (e.g. "1 (795-gram) can").
    Falls back to 1 for incompatible or unparseable units.
    """
    UNIT_FACTORS = {
        # Metric weight
        'kg': 1000, 'kilogram': 1000, 'kilograms': 1000,
        'g': 1,     'gram': 1,        'grams': 1,
        # Metric volume
        'l': 1000,  'liter': 1000,    'liters': 1000,  'litre': 1000,  'litres': 1000,
        'ml': 1,    'milliliter': 1,  'milliliters': 1, 'millilitre': 1, 'millilitres': 1,
        # Imperial weight (converted to grams)
        'lb': 453.592, 'lbs': 453.592, 'pound': 453.592, 'pounds': 453.592,
        'oz': 28.3495, 'ounce': 28.3495, 'ounces': 28.3495,
        # Imperial volume (converted to ml)
        'cup': 240,   'cups': 240,
        'tbsp': 15,   'tablespoon': 15,   'tablespoons': 15,
        'tsp': 5,     'teaspoon': 5,      'teaspoons': 5,
        'pint': 473.176, 'pints': 473.176,
        'quart': 946.353, 'quarts': 946.353,
    }
    WEIGHT_UNITS = {
        'kg', 'kilogram', 'kilograms', 'g', 'gram', 'grams',
        'lb', 'lbs', 'pound', 'pounds', 'oz', 'ounce', 'ounces',
    }
    TOLERANCE = 0.85

    # Longer alternatives must come before shorter ones to avoid partial matches.
    _unit_pat = (
        r'(tablespoon(?:s)?|tbsp'
        r'|teaspoon(?:s)?|tsp'
        r'|pound(?:s)?|lbs?'
        r'|ounce(?:s)?|oz'
        r'|quart(?:s)?'
        r'|pint(?:s)?'
        r'|cup(?:s)?'
        r'|kilogram(?:s)?|kg'
        r'|gram(?:s)?|g'
        r'|millilitre(?:s)?|milliliter(?:s)?|ml'
        r'|litre(?:s)?|liter(?:s)?|l)'
    )

    def parse_total(s: str):
        s = s.lower().replace(',', '.')
        matches = re.findall(rf'([\d.]+)[\s-]*{_unit_pat}\b', s)
        if not matches:
            return None
        weight, volume = 0.0, 0.0
        for num_str, unit in matches:
            val = float(num_str) * UNIT_FACTORS[unit]
            if unit in WEIGHT_UNITS:
                weight += val
            else:
                volume += val
        if weight > 0 and volume == 0:
            return weight, 'weight'
        if volume > 0 and weight == 0:
            return volume, 'volume'
        return None  # mixed units — can't reliably sum

    ing = parse_total(ingredient_qty_str)
    pkg = parse_total(package_size_str) or parse_total(product_name_str)

    if ing and pkg and ing[1] == pkg[1] and pkg[0] > 0:
        needed, pack = ing[0], pkg[0]
        n_floor = max(1, math.floor(needed / pack))
        if n_floor * pack >= needed * TOLERANCE:
            return n_floor
        return math.ceil(needed / pack)
    return 1


def fetch_item_from_rohlik(item: dict) -> dict:
    """
    Fetch the top 3 Rohlik product alternatives for a single ingredient.

    Thread-safe: acquires a lock before initialising the MCP agent to avoid
    rate-limit collisions when called from a ThreadPoolExecutor.
    """
    with _init_lock:
        time.sleep(4.0)
        try:
            agent = RohlikMCPAgent()
        except Exception as e:
            raise RuntimeError(f"Failed to initialise Rohlik agent: {e}")

    try:
        search_term = apply_search_preferences(item['name'])
        alternatives = agent.find_alternatives(search_term)
    except Exception as e:
        raise RuntimeError(f"Agent failed to find alternatives: {e}")

    return {
        "ingredient": item['name'],
        "search_term": search_term,
        "quantity_needed": item['quantity'],
        "options": alternatives,
    }

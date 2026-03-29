import os
import json
from pypdf import PdfReader
from google import genai

def extract_text_from_pdf(pdf_source):
    """
    Extracts text from a structured PDF document.
    
    Args:
        pdf_source: A file path or file-like object representing the PDF.
        
    Returns:
        A single string containing the concatenated text from all pages.
    """
    try:
        reader = PdfReader(pdf_source)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Failed to read PDF source: {e}")
        return ""

def parse_recipe_ingredients(recipe_text, api_key):
    """
    Uses the Gemini LLM to parse raw recipe text into a structured JSON list of ingredients.
    
    Args:
        recipe_text (str): The raw text extracted from a recipe document.
        api_key (str): The API key for Gemini.
        
    Returns:
        list: A list of dicts, each with 'name' and 'quantity' keys. Returns an empty list on failure. 
    """
    try:
        client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})
        prompt = (
            "Extract a JSON list of ingredients from the following recipe text. "
            "Include name and quantity for each. "
            "Return ONLY a raw JSON array of objects with keys 'name' and 'quantity'.\n\n"
            f"Recipe Text:\n{recipe_text}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        text_out = response.text.strip()
        # Clean up markdown code blocks if the LLM includes them
        if text_out.startswith("```json"):
            text_out = text_out[7:-3].strip()
        elif text_out.startswith("```"):
            text_out = text_out[3:-3].strip()
        
        return json.loads(text_out)
    except Exception as e:
        print(f"Error communicating with Gemini or parsing JSON output: {e}")
        return []

def consolidate_ingredients(recipe_ingredient_lists):
    """
    Consolidates multiple lists of ingredients into a single, grouped list.
    Merges items with the identical lowercase names and attempts to concatenate their quantities.
    
    Args:
        recipe_ingredient_lists (list): A list of lists of standard ingredient dicts.
        
    Returns:
        list: A deduplicated, consolidated list of ingredient dicts.
    """
    consolidated = {}
    
    for ing_list in recipe_ingredient_lists:
        for ing in ing_list:
            name_raw = ing.get('name')
            if not name_raw:
                continue
            name = str(name_raw).lower().strip()
            
            qty_raw = ing.get('quantity')
            qty = str(qty_raw).strip() if qty_raw is not None else ""
            
            if name in consolidated:
                # Simple concatenation for now, can be improved with unit parsing
                consolidated[name]['quantity'] += f" + {qty}"
            else:
                consolidated[name] = {
                    "name": ing['name'], # Keep original casing for display
                    "quantity": qty
                }
                
    return list(consolidated.values())

def filter_pantry_items(ingredients, pantry_path):
    """
    Filters out ingredients that are already present in the user's pantry manifest.
    
    Args:
        ingredients (list): Standard list of needed ingredients via parses.
        pantry_path (str): The file path to the user's markdown pantry manifest.
        
    Returns:
        tuple: (needed_ingredients, matched_ingredients_for_confirmation)
    """
    if not os.path.exists(pantry_path):
        return ingredients, []
    
    with open(pantry_path, "r") as f:
        # Assumes pantry manifest is a markdown list: - item name
        pantry_items = [line.strip("- ").lower().strip() for line in f if line.strip().startswith("-")]
    
    import re
    needed = []
    matched = []
    for ing in ingredients:
        ing_name = ing['name'].lower().strip()
        match_found = False
        matched_item_name = ""
        
        for p_item in pantry_items:
            if not p_item: continue
            # Use word boundaries so "salt" matches "kosher salt" but "water" doesn't match "watermelon"
            if re.search(r'\b' + re.escape(p_item) + r'\b', ing_name):
                match_found = True
                matched_item_name = p_item
                break
                
        if not match_found:
            needed.append(ing)
        else:
            matched.append({"ingredient": ing, "matched_pantry_item": matched_item_name})
            
    return needed, matched

def apply_search_preferences(ingredient_name, preferences_path):
    """
    Checks user preferences for explicit 'search instead' rules.
    Example Rule: '- When you see \'garlic cloves\', search \'garlic\''
    
    Args:
        ingredient_name (str): The original ingredient name.
        preferences_path (str): Path to the preferences.md file.
        
    Returns:
        str: The mapped search term or the original name if no rule matches.
    """
    if not os.path.exists(preferences_path):
        return ingredient_name
        
    import re
    ing_lower = ingredient_name.lower().strip()
    
    with open(preferences_path, "r") as f:
        for line in f:
            # Look for patterns like: When you see 'X', search 'Y' or When you see 'X', look for 'Y'
            match = re.search(r"When you see ['\"](.+?)['\"], (?:search|look for) ['\"](.+?)['\"]", line, re.IGNORECASE)
            if match:
                target = match.group(1).lower().strip()
                replacement = match.group(2).strip()
                if ing_lower == target:
                    return replacement
                    
    return ingredient_name

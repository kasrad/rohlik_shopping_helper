import io
import json
import re
from pypdf import PdfReader
import anthropic

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

def extract_text_from_markdown(md_source) -> str:
    """
    Extracts recipe text from a markdown file.

    For NYT Cooking recipes (source contains cooking.nytimes.com), only the
    ## Ingredients section is returned to minimise token usage.

    Args:
        md_source: A file path, file-like object, or string with markdown content.

    Returns:
        A string with the relevant recipe text.
    """
    if isinstance(md_source, str):
        content = md_source
    elif isinstance(md_source, (bytes, bytearray)):
        content = md_source.decode("utf-8")
    else:
        raw = md_source.read()
        content = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw

    # Detect NYT Cooking source from YAML frontmatter
    is_nyt = bool(re.search(r'^source:\s*["\']?https?://cooking\.nytimes\.com', content, re.MULTILINE | re.IGNORECASE))

    if is_nyt:
        # Extract only the Ingredients section (up to next ## heading or end of file)
        match = re.search(r'##\s+Ingredients\s*\n(.*?)(?=\n##\s|\Z)', content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(0).strip()

    return content


def parse_recipe_ingredients(recipe_text, api_key):
    """
    Uses Claude to parse raw recipe text into a structured JSON list of ingredients.

    Args:
        recipe_text (str): The raw text extracted from a recipe document.
        api_key (str): The Anthropic API key.

    Returns:
        list: A list of dicts, each with 'name' and 'quantity' keys.

    Raises:
        ValueError: If the source appears to contain no extractable text.
        RuntimeError: If the Claude API call or JSON parsing fails.
    """
    if not recipe_text or not recipe_text.strip():
        raise ValueError(
            "No text could be extracted from this PDF. "
            "It may be a scanned image rather than a text-based PDF."
        )

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "Extract a JSON list of ingredients from the following recipe text. "
        "Include name and quantity for each. "
        "Return ONLY a raw JSON array of objects with keys 'name' and 'quantity'.\n\n"
        f"Recipe Text:\n{recipe_text}"
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        raise RuntimeError(f"Claude API call failed: {e}") from e

    text_out = response.content[0].text if response.content else None
    if not text_out:
        raise RuntimeError(
            "Claude returned an empty response. "
            "The model may have hit a safety filter or a rate limit."
        )

    text_out = text_out.strip()
    if text_out.startswith("```json"):
        text_out = text_out[7:].rstrip("`").strip()
    elif text_out.startswith("```"):
        text_out = text_out[3:].rstrip("`").strip()

    # Direct parse
    try:
        return json.loads(text_out)
    except json.JSONDecodeError:
        pass

    # Fallback: find a JSON array anywhere in the response
    match = re.search(r'\[.*\]', text_out, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Could not parse Claude response as JSON.\nResponse was: {text_out[:300]}"
    )

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


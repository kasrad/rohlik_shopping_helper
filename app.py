import streamlit as st
import os
import urllib.parse
import json
import concurrent.futures
import threading
import time
import pandas as pd
from dotenv import load_dotenv

from processor import extract_text_from_pdf, parse_recipe_ingredients, consolidate_ingredients, filter_pantry_items, apply_search_preferences
from agents.mcp_agent import RohlikMCPAgent

# ------------------------------------------------------------------------
# Initialization & Setup
# ------------------------------------------------------------------------
load_dotenv("/Users/radim/personal/rohlik_nyt_agent/.env")
api_key = os.environ.get("GEMINI_API_KEY")
pantry_path = "/Users/radim/personal/rohlik_nyt_agent/pantry_manifest.md"

st.set_page_config(page_title="Rohlik Shopping Agent", page_icon="🛒", layout="wide")

# We use a lock for thread-safe MCP agent initialization to avoid hitting
# rate limits or causing unhandled Node.js subprocess errors.
init_lock = threading.Lock()

# Initialize session state for UI stability
if 'extraction_summary' not in st.session_state:
    st.session_state.extraction_summary = None

# ------------------------------------------------------------------------
# UI Components
# ------------------------------------------------------------------------

def render_upload_section():
    """Handles PDF file uploads and processes them to extract ingredients."""
    st.title("🛒 Rohlik Shopping Agent")
    st.markdown("### Iteration 2: Multi-PDF Recipe Consolidation")
    st.write("Upload up to 10 recipe PDFs to generate a consolidated shopping list.")

    uploaded_files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)

    # Persistent summary display to keep the widget tree stable
    if st.session_state.extraction_summary:
        st.info(st.session_state.extraction_summary)

    if uploaded_files:
        if len(uploaded_files) > 10:
            st.warning("Please upload a maximum of 10 files. Only the first 10 will be processed.")
            uploaded_files = uploaded_files[:10]
        
        if st.button("Generate Consolidated List"):
            all_recipe_ingredients = []
            
            # Use a status block for a stable processing UI
            with st.status("Processing recipes...", expanded=True) as status:
                for i, uploaded_file in enumerate(uploaded_files):
                    st.write(f"Reading: **{uploaded_file.name}**...")
                    try:
                        text = extract_text_from_pdf(uploaded_file)
                        ingredients = parse_recipe_ingredients(text, api_key)
                        if ingredients:
                            all_recipe_ingredients.append(ingredients)
                            st.write(f"✅ Extracted {len(ingredients)} ingredients from {uploaded_file.name}")
                        else:
                            st.error(f"❌ Failed to parse ingredients from {uploaded_file.name}")
                    except Exception as e:
                        st.error(f"❌ Error reading {uploaded_file.name}: {e}")
                
                if all_recipe_ingredients:
                    try:
                        consolidated = consolidate_ingredients(all_recipe_ingredients)
                        needed, matched = filter_pantry_items(consolidated, pantry_path)
                        
                        st.session_state.base_needed = needed
                        st.session_state.matched = matched
                        st.session_state.pantry_overrides = {}
                        st.session_state.shopping_list = None 
                        st.session_state.selections = {}
                        
                        summary = f"Successfully processed {len(all_recipe_ingredients)} recipes! Found {len(consolidated)} unique ingredients."
                        st.session_state.extraction_summary = summary
                        status.update(label="Recipes processed!", state="complete", expanded=False)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error while consolidating: {e}")
                        status.update(label="Processing failed", state="error")
                else:
                    st.error("No ingredients could be parsed from the uploaded files.")
                    status.update(label="Processing failed", state="error")
    else:
        st.info("Please upload at least one PDF recipe to get started.")

def render_pantry_match_tab():
    st.subheader("🧐 Pantry Match")
    st.write("We found these ingredients in your pantry manifest. Uncheck any items you actually need to buy.")
    
    if not st.session_state.matched:
        st.info("No items matched your pantry. Nothing to review here!")
        return

    for i, match in enumerate(st.session_state.matched):
        ing_name = match['ingredient']['name']
        qty = match['ingredient']['quantity']
        p_item = match['matched_pantry_item']
        
        current_val = st.session_state.pantry_overrides.get(ing_name, True)
        
        def on_change_pantry(name=ing_name, key=f"pantry_cb_{i}"):
            st.session_state.pantry_overrides[name] = st.session_state[key]
            # Reset shopping list when pantry changes so we don't end up with stale data
            st.session_state.shopping_list = None
            
        st.checkbox(
            f"**{ing_name}** ({qty}) — *Matched rule: {p_item}*",
            value=current_val,
            key=f"pantry_cb_{i}",
            on_change=on_change_pantry
        )

def _fetch_item_from_rohlik(item: dict) -> dict:
    """Helper method to fetch alternatives for an ingredient safely via Rohlik MCP."""
    with init_lock:
        time.sleep(4.0)
        try:
            agent = RohlikMCPAgent()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Rohlik agent: {e}")
        
    try:
        # Apply search preferences (e.g., 'garlic cloves' -> 'garlic')
        # We need the relative path to preferences.md
        prefs_path = "/Users/radim/personal/rohlik_nyt_agent/preferences.md"
        search_term = apply_search_preferences(item['name'], prefs_path)
        alternatives = agent.find_alternatives(search_term)
    except Exception as e:
        raise RuntimeError(f"Agent failed to find alternatives: {e}")

    return {
        "ingredient": item['name'],
        "search_term": search_term, # Keep track of what we actually searched
        "quantity_needed": item['quantity'],
        "options": alternatives
    }

def render_rohlik_search_tab():
    st.subheader("🔍 Rohlik Product Search")
    needed = st.session_state.effective_needed
    
    if not needed:
        st.success("All ingredients are covered by your pantry!")
        return
        
    needs_fetching = st.session_state.get('shopping_list') is None
    
    if needs_fetching:
        st.info(f"You need to buy {len(needed)} items.")
        
        # Text download output
        txt_output = "🛒 CONSOLIDATED SHOPPING LIST\n\n"
        for item in needed:
            txt_output += f"- {item['name']}: {item['quantity']}\n"
        
        st.download_button(
            label="Download List (.txt)",
            data=txt_output,
            file_name="consolidated_shopping_list.txt",
            mime="text/plain"
        )
        
        if st.button("Find Products on Rohlik.cz", use_container_width=True):
            shopping_list = []
            
            # Using st.status to prevent "ghosting" and keep UI clean
            with st.status("🔍 Sourcing Products from Rohlik.cz...", expanded=True) as status:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(_fetch_item_from_rohlik, item): item for item in needed}
                    for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                        item_failed = futures[future]
                        try:
                            result = future.result()
                            shopping_list.append(result)
                            st.write(f"✅ Fetched: {item_failed['name']}")
                        except Exception as e:
                            st.error(f"❌ Error fetching '{item_failed['name']}': {e}")
                
                st.session_state.shopping_list = shopping_list
                status.update(label=f"Sourced {len(shopping_list)} products!", state="complete", expanded=False)
                
            st.rerun()

    if not needs_fetching:
        st.success(f"Sourced {len(st.session_state.shopping_list)} products! Select your preferred options.")
        if st.button("Refetch All Products"):
            st.session_state.shopping_list = None
            st.rerun()
            
        st.markdown("---")
        for i, item in enumerate(st.session_state.shopping_list):
            title = item['ingredient']
            if item.get('search_term') and item['search_term'].lower() != item['ingredient'].lower():
                title += f" (Searched as: **{item['search_term']}**)"
            
            st.markdown(f"#### {title} (Needed: {item['quantity_needed']})")
            
            options = item.get('options', [])
            if not options:
                st.warning("No alternatives found.")
                
                # Add a refetch button for single items
                if st.button(f"🔄 Refetch {item['ingredient']}", key=f"refetch_{i}"):
                    with st.spinner(f"Refetching {item['ingredient']}..."):
                        try:
                            fetch_arg = {"name": item["ingredient"], "quantity": item["quantity_needed"]}
                            # Re-fetch the item
                            new_data = _fetch_item_from_rohlik(fetch_arg)
                            # Update the shopping list
                            st.session_state.shopping_list[i] = new_data
                            # Reset selection value safely
                            st.session_state.selections[item['ingredient']] = 0
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to refetch: {e}")
                
                search_name = item.get('search_term', item['ingredient'])
                encoded_ingredient = urllib.parse.quote(search_name + " ")
                search_url = f"https://www.rohlik.cz/en-CZ/hledat?q={encoded_ingredient}&companyId=1"
                st.markdown(f"[View Search on Rohlik]({search_url})")
                st.session_state.selections[item['ingredient']] = -1 # Special code for skipped
                st.markdown("---")
                continue
                
            formatted_options = []
            for opt in options:
                name = opt.get('name', 'Unknown')
                price = opt.get('price', 'N/A')
                ppu = opt.get('price_per_unit', 'N/A')
                pkg = opt.get('package_size', 'N/A')
                formatted_options.append(f"**{name}** ({pkg}) - {price} Kč ({ppu})")
                
            SKIP_OPTION = "🚫 Don't add anything"
            formatted_options.append(SKIP_OPTION)
                
            current_idx = st.session_state.selections.get(item['ingredient'], 0)
            if current_idx == -1: 
                current_idx = len(formatted_options) - 1 # Map -1 to SKIP_OPTION

            def on_change_selection(ing=item['ingredient'], key=f"radio_{i}", opts=formatted_options):
                if key not in st.session_state:
                    return
                sel_str = st.session_state[key]
                if sel_str == SKIP_OPTION:
                    st.session_state.selections[ing] = -1
                else:
                    try:
                        st.session_state.selections[ing] = opts.index(sel_str)
                    except ValueError:
                        # This can happen if the options changed between re-runs
                        # We'll default to the first option if it's completely out of sync
                        st.session_state.selections[ing] = 0
            
            selected_str = st.radio(
                "Choose an option:",
                options=formatted_options,
                index=current_idx,
                key=f"radio_{i}",
                label_visibility="collapsed",
                on_change=on_change_selection
            )
            
            # Use search_term for the link if available
            search_name = item.get('search_term', item['ingredient'])
            encoded_ingredient = urllib.parse.quote(search_name + " ")
            search_url = f"https://www.rohlik.cz/en-CZ/hledat?q={encoded_ingredient}&companyId=1"
            st.markdown(f"[View on Rohlik]({search_url})")
            st.markdown("---")

def render_cart_summary_tab():
    st.subheader("🛒 Final Cart SUMMARY")
    if st.session_state.get('shopping_list') is None:
        st.info("Fetch products in the 'Rohlik Search' tab first.")
        return
        
    final_selections = []
    cart_items = []
    skipped_items_final = []
    
    for item in st.session_state.shopping_list:
        ing = item['ingredient']
        sel_idx = st.session_state.selections.get(ing, 0)
        options = item.get('options', [])
        
        if not options or sel_idx == -1:
            skipped_items_final.append({"Ingredient": ing, "Reason": "Nothing found" if not options else "Skipped"})
            continue
            
        selected_option = options[sel_idx]
        search_name = item.get('search_term', ing)
        encoded_ingredient = urllib.parse.quote(search_name + " ")
        search_url = f"https://www.rohlik.cz/en-CZ/hledat?q={encoded_ingredient}&companyId=1"
        
        final_selections.append({
            "ingredient": ing,
            "quantity": item['quantity_needed'],
            "product_name": selected_option.get('name'),
            "product_id": selected_option.get('product_id'),
            "package_size": selected_option.get('package_size'),
            "price": selected_option.get('price'),
            "price_per_unit": selected_option.get('price_per_unit'),
            "url": search_url
        })
        
        prod_id = selected_option.get('product_id')
        if prod_id:
            cart_items.append({
                "productId": int(prod_id),
                "quantity": 1
            })
            
    try:
        total_price = sum(float(str(sel.get('price', 0)).replace(',','').replace('Kč','').strip() or 0) for sel in final_selections)
    except Exception:
        total_price = 0.0
        
    st.markdown(f"### Estimated Total: {total_price:.2f} Kč")
    
    if st.button("🛒 Add to basket", use_container_width=True):
        if not cart_items:
            st.warning("No items selected to add to the basket.")
        else:
            with st.spinner("Adding items to your Rohlik.cz basket..."):
                try:
                    cart_agent = RohlikMCPAgent()
                    result = cart_agent.add_items_to_basket(cart_items)
                    
                    st.success("Successfully added selected items to your Rohlik basket!")
                    with st.expander("View Agent Output"):
                        st.code(result)
                        
                    out_path_json = "/Users/radim/personal/rohlik_nyt_agent/final_selections.json"
                    with open(out_path_json, "w") as f:
                        json.dump(final_selections, f, indent=2, ensure_ascii=False)
                    
                    st.balloons()
                except Exception as e:
                    st.error(f"A critical error occurred while adding items to the basket: {e}")
                    
    st.markdown("---")
    st.markdown("#### Items to Buy")
    if final_selections:
        df_buy = pd.DataFrame(final_selections)
        st.table(df_buy[['ingredient', 'quantity', 'product_name', 'price', 'price_per_unit']])
    else:
        st.info("No items selected.")
        
    st.markdown("#### Items Skipped / Ignored")
    val_skipped = list(skipped_items_final)
    # Also include items ignored from Pantry
    if 'matched' in st.session_state:
        for m in st.session_state.matched:
            ing_name = m['ingredient']['name']
            if st.session_state.pantry_overrides.get(ing_name, True):
                val_skipped.append({"Ingredient": ing_name, "Reason": f"In Pantry (Rule: {m['matched_pantry_item']})"})
                
    if val_skipped:
        df_skipped = pd.DataFrame(val_skipped)
        st.table(df_skipped)

# ------------------------------------------------------------------------
# Main Application Flow
# ------------------------------------------------------------------------
def main():
    render_upload_section()
    
    if 'base_needed' in st.session_state and 'matched' in st.session_state:
        # Compute effective needed
        effective_needed = list(st.session_state.base_needed)
        for m in st.session_state.matched:
            ing_name = m['ingredient']['name']
            has_it = st.session_state.pantry_overrides.get(ing_name, True)
            if not has_it:
                effective_needed.append(m['ingredient'])
                
        st.session_state.effective_needed = effective_needed
        
        st.markdown("---")
        tab1, tab2, tab3 = st.tabs(["📋 Pantry Match", "🔍 Rohlik Search", "🛒 Final Cart SUMMARY"])
        
        with tab1:
            render_pantry_match_tab()
            
        with tab2:
            render_rohlik_search_tab()
            
        with tab3:
            render_cart_summary_tab()

if __name__ == "__main__":
    main()

import streamlit as st
import os
import urllib.parse
import json
import concurrent.futures
import threading
import time
import pandas as pd
from dotenv import load_dotenv

from processor import extract_text_from_pdf, parse_recipe_ingredients, consolidate_ingredients, filter_pantry_items
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

# ------------------------------------------------------------------------
# UI Components
# ------------------------------------------------------------------------

def render_upload_section():
    """Handles PDF file uploads and processes them to extract ingredients."""
    st.title("🛒 Rohlik Shopping Agent")
    st.markdown("### Iteration 2: Multi-PDF Recipe Consolidation")
    st.write("Upload up to 10 recipe PDFs to generate a consolidated shopping list.")

    uploaded_files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)

    if uploaded_files:
        if len(uploaded_files) > 10:
            st.warning("Please upload a maximum of 10 files. Only the first 10 will be processed.")
            uploaded_files = uploaded_files[:10]
        
        if st.button("Generate Consolidated List"):
            all_recipe_ingredients = []
            progress_bar = st.progress(0)
            
            for i, uploaded_file in enumerate(uploaded_files):
                st.write(f"Processing: **{uploaded_file.name}**...")
                try:
                    text = extract_text_from_pdf(uploaded_file)
                    ingredients = parse_recipe_ingredients(text, api_key)
                    if ingredients:
                        all_recipe_ingredients.append(ingredients)
                        st.success(f"Extracted {len(ingredients)} ingredients from {uploaded_file.name}")
                    else:
                        st.error(f"Failed to parse ingredients from {uploaded_file.name}. Ensure it contains a valid recipe.")
                except Exception as e:
                    st.error(f"Error reading file {uploaded_file.name}: {e}")
                
                progress_bar.progress((i + 1) / len(uploaded_files))
                
            if all_recipe_ingredients:
                try:
                    consolidated = consolidate_ingredients(all_recipe_ingredients)
                    needed, matched = filter_pantry_items(consolidated, pantry_path)
                    
                    st.session_state.needed_ingredients = needed
                    st.session_state.matched_ingredients = matched
                    st.session_state.pantry_confirmed = False
                    st.session_state.in_pantry_items = []
                    # Reset selections if we generate a new list
                    st.session_state.shopping_list = None 
                except Exception as e:
                    st.error(f"Error while consolidating or filtering pantry items: {e}")
            else:
                st.error("No ingredients could be parsed from the uploaded files.")
    else:
        st.info("Please upload at least one PDF recipe to get started.")

def render_pantry_check():
    """Renders the pantry confirmation UI to ensure the user really has matched items."""
    if 'matched_ingredients' in st.session_state and not st.session_state.get('pantry_confirmed', True):
        st.markdown("---")
        st.subheader("🧐 Pantry Check")
        
        if len(st.session_state.matched_ingredients) > 0:
            st.write("We found these ingredients in your pantry. Please confirm if you really have them:")
            with st.form("pantry_check_form"):
                confirm_results = []
                for i, match in enumerate(st.session_state.matched_ingredients):
                    ing_name = match['ingredient']['name']
                    qty = match['ingredient']['quantity']
                    p_item = match['matched_pantry_item']
                    
                    choice = st.radio(
                        f"Do you have **{ing_name}** ({qty})? (Matched pantry rule: *{p_item}*)",
                        options=["Yes, I have it (Skip buying)", "No, I need to buy it"],
                        key=f"pantry_check_{i}"
                    )
                    confirm_results.append((match['ingredient'], choice))
                
                submitted = st.form_submit_button("Confirm & Proceed to Sourcing")
                if submitted:
                    for ing, choice in confirm_results:
                        if "No, I need to buy it" in choice:
                            st.session_state.needed_ingredients.append(ing)
                        else:
                            st.session_state.in_pantry_items.append({"Ingredient": ing['name'], "Reason": "In Pantry Manifest (Confirmed)"})
                    st.session_state.pantry_confirmed = True
                    st.rerun()
        else:
            # If nothing matched, skip automatically
            st.session_state.pantry_confirmed = True
            st.rerun()

def _fetch_item_from_rohlik(item: dict) -> dict:
    """Helper method to fetch alternatives for an ingredient safely via Rohlik MCP."""
    with init_lock:
        # Heavily stagger requests to prevent rate-limits and MCP server crashes
        time.sleep(4.0)
        try:
            agent = RohlikMCPAgent()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Rohlik agent: {e}")
        
    try:
        alternatives = agent.find_alternatives(item['name'])
    except Exception as e:
        raise RuntimeError(f"Agent failed to find alternatives: {e}")

    return {
        "ingredient": item['name'],
        "quantity_needed": item['quantity'],
        "options": alternatives,
        "selected_index": 0 
    }

def render_sourcing_section():
    """Handles displaying the consolidated ingredients and sourcing them from Rohlik."""
    if 'needed_ingredients' in st.session_state and st.session_state.get('pantry_confirmed', False):
        needed = st.session_state.needed_ingredients
        
        st.subheader("Consolidated Ingredients (All Recipes)")
        if not needed:
            st.success("All ingredients are already in your pantry!")
            return

        st.info(f"Filtered out items found in `{os.path.basename(pantry_path)}`")
        
        # Download button for TXT
        txt_output = "🛒 CONSOLIDATED SHOPPING LIST\n\n"
        for item in needed:
            txt_output += f"- {item['name']}: {item['quantity']}\n"
        
        st.download_button(
            label="Download List (.txt)",
            data=txt_output,
            file_name="consolidated_shopping_list.txt",
            mime="text/plain"
        )
        
        if st.session_state.get('shopping_list') is None:
            st.table(needed)
            if st.button("Find Products on Rohlik.cz"):
                shopping_list = []
                sourcing_bar = st.progress(0)
                status_text = st.empty()
                status_text.text("Searching Rohlik for ingredients concurrently (staggering connections incrementally to prevent timeouts)...")
                
                # Execute concurrently with robust error handling
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(_fetch_item_from_rohlik, item): item for item in needed}
                    for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                        item_failed = futures[future]
                        try:
                            result = future.result()
                            shopping_list.append(result)
                        except Exception as e:
                            st.error(f"Error fetching product '{item_failed['name']}': {e}")
                        
                        sourcing_bar.progress((idx + 1) / len(needed))
                
                status_text.text("Sourcing complete!")
                st.session_state.shopping_list = shopping_list
                st.rerun()

def render_selection_ui():
    """Renders the shopping list selection interface and the checkout logic."""
    if st.session_state.get('shopping_list') is not None:
        st.markdown("---")
        st.header("🛍️ Select Your Products")
        
        final_selections = []
        cart_items = []
        skipped_items_final = list(st.session_state.get('in_pantry_items', []))
        
        for i, item in enumerate(st.session_state.shopping_list):
            st.subheader(f"{item['ingredient']} (Needed: {item['quantity_needed']})")
            
            options = item.get('options', [])
            if not options:
                st.warning("No alternatives found.")
                
                encoded_ingredient = urllib.parse.quote(item['ingredient'] + " ")
                search_url = f"https://www.rohlik.cz/en-CZ/hledat?q={encoded_ingredient}&companyId=1"
                st.markdown(f"[View Search on Rohlik]({search_url})")
                
                skipped_items_final.append({"Ingredient": item['ingredient'], "Reason": "Nothing Found on Rohlik"})
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
                
            default_idx = min(item.get('selected_index', 0), len(options))
            
            selected_str = st.radio(
                "Choose an option:",
                options=formatted_options,
                index=default_idx,
                key=f"radio_{i}",
                label_visibility="collapsed"
            )
            
            selected_idx = formatted_options.index(selected_str)
            st.session_state.shopping_list[i]['selected_index'] = selected_idx
            
            if selected_str == SKIP_OPTION:
                st.markdown("*Skipping this item.*")
                st.markdown("---")
                skipped_items_final.append({"Ingredient": item['ingredient'], "Reason": "Skipped ('Don't add anything')"})
                continue
                
            selected_option = options[selected_idx]
            
            encoded_ingredient = urllib.parse.quote(item['ingredient'] + " ")
            search_url = f"https://www.rohlik.cz/en-CZ/hledat?q={encoded_ingredient}&companyId=1"
            
            final_selections.append({
                "ingredient": item['ingredient'],
                "quantity": item['quantity_needed'],
                "product_name": selected_option.get('name'),
                "product_id": selected_option.get('product_id'),
                "package_size": selected_option.get('package_size'),
                "price": selected_option.get('price'),
                "url": search_url
            })
            
            prod_id = selected_option.get('product_id')
            if prod_id:
                cart_items.append({
                    "productId": int(prod_id),
                    "quantity": 1 # Defaulting to 1 for automated cart
                })
            
            st.markdown(f"[View on Rohlik]({search_url})")
            st.markdown("---")
        
        # --------------------------------------------------------------------
        # Checkout Sequence
        # --------------------------------------------------------------------
        st.header("Total Summary")
        try:
            total_price = sum(float(str(sel.get('price', 0)).replace(',','').replace('Kč','').strip() or 0) for sel in final_selections)
        except Exception:
            total_price = 0.0
            
        st.subheader(f"Estimated Total: {total_price:.2f} Kč")
        
        if st.button("🛒 Add to basket"):
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
                            
                        # Save state for future runs or verification
                        out_path_json = "/Users/radim/personal/rohlik_nyt_agent/final_selections.json"
                        with open(out_path_json, "w") as f:
                            json.dump(final_selections, f, indent=2, ensure_ascii=False)
                        
                        out_path_md = "/Users/radim/personal/rohlik_nyt_agent/interactive_shopping_list.md"
                        with open(out_path_md, "w") as f:
                            f.write("# 🛒 Final Interactive Shopping List\n\n")
                            for sel in final_selections:
                                f.write(f"* **{sel['ingredient']}** ({sel['quantity']}): [{sel['product_name']}]({sel['url']}) - **{sel['price']} Kč**\n")
                            f.write(f"\n**Total: {total_price:.2f} Kč**\n")
                        
                        st.balloons()
                    except Exception as e:
                        st.error(f"A critical error occurred while adding items to the basket: {e}")
                        st.info("Please check the console logs for more information.")
                
                st.markdown("---")
                st.header("📋 Items Excluded from Basket")
                if skipped_items_final:
                    df_skipped = pd.DataFrame(skipped_items_final)
                    st.table(df_skipped)
                else:
                    st.info("No items were excluded! Everything from the recipes was added to your cart.")

# ------------------------------------------------------------------------
# Main Application Flow
# ------------------------------------------------------------------------
def main():
    render_upload_section()
    render_pantry_check()
    render_sourcing_section()
    render_selection_ui()

if __name__ == "__main__":
    main()

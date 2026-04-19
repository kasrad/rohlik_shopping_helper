import streamlit as st
import os
import urllib.parse
import json
import concurrent.futures
import pandas as pd
from dotenv import load_dotenv

from config import ENV_PATH, PANTRY_PATH, ROOT
from processor import extract_text_from_pdf, extract_text_from_markdown, parse_recipe_ingredients, consolidate_ingredients
from pantry import filter_pantry_items
from shopping import fetch_item_from_rohlik, _auto_suggest_quantity
from agents.mcp_agent import RohlikMCPAgent

# ------------------------------------------------------------------------
# Initialization & Setup
# ------------------------------------------------------------------------
load_dotenv(ENV_PATH, override=True)
api_key = os.environ.get("ANTHROPIC_API_KEY")

st.set_page_config(page_title="Rohlik Shopping Agent", page_icon="🛒", layout="wide")

# Initialize session state for UI stability
if 'extraction_summary' not in st.session_state:
    st.session_state.extraction_summary = None
if 'quantities' not in st.session_state:
    st.session_state.quantities = {}

# ------------------------------------------------------------------------
# UI Components
# ------------------------------------------------------------------------

def render_upload_section():
    """Handles recipe file uploads (PDF or .md) and processes them to extract ingredients."""
    col_title, col_reset = st.columns([6, 1])
    with col_title:
        st.title("🛒 Rohlik Shopping Agent")
    with col_reset:
        if 'base_needed' in st.session_state:
            st.write("")  # vertical alignment nudge
            if st.button("↩ Start Over", type="secondary", use_container_width=True):
                for key in ['base_needed', 'matched', 'pantry_overrides', 'shopping_list',
                            'selections', 'quantities', 'extraction_summary', 'effective_needed']:
                    st.session_state.pop(key, None)
                st.rerun()
    st.write("Upload up to 10 recipe files (PDF or Markdown) to generate a consolidated shopping list.")

    # Accept PDFs and Markdown files. Markdown MIME type varies by OS/browser
    # (text/markdown or text/plain), so we allow both and rely on the .md
    # extension check in the processing loop to route correctly.
    uploaded_files = st.file_uploader(
        "Choose recipe files",
        type=["pdf", "text/markdown", "text/plain", "md"],
        accept_multiple_files=True,
    )

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
                        if uploaded_file.name.lower().endswith(".md"):
                            text = extract_text_from_markdown(uploaded_file)
                        else:
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
                        needed, matched = filter_pantry_items(consolidated)
                        
                        st.session_state.base_needed = needed
                        st.session_state.matched = matched
                        st.session_state.pantry_overrides = {}
                        st.session_state.shopping_list = None
                        st.session_state.selections = {}
                        st.session_state.quantities = {}
                        
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
        st.info("Please upload at least one recipe file (PDF or Markdown) to get started.")

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
                total = len(needed)
                progress_bar = st.progress(0, text=f"0 / {total} products fetched")
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(fetch_item_from_rohlik, item): item for item in needed}
                    for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                        item_failed = futures[future]
                        try:
                            result = future.result()
                            shopping_list.append(result)
                            st.write(f"✅ Fetched: {item_failed['name']}")
                        except Exception as e:
                            st.error(f"❌ Error fetching '{item_failed['name']}': {e}")
                        progress_bar.progress((idx + 1) / total, text=f"{idx + 1} / {total} products fetched")

                st.session_state.shopping_list = shopping_list
                status.update(label=f"Sourced {len(shopping_list)} products!", state="complete", expanded=False)
                
            st.rerun()

    if not needs_fetching:
        st.success(f"Sourced {len(st.session_state.shopping_list)} products! Select your preferred options.")
        if st.button("Refetch All Products"):
            st.session_state.shopping_list = None
            st.session_state.quantities = {}
            st.rerun()
            
        st.markdown("---")
        for i, item in enumerate(st.session_state.shopping_list):
            title = item['ingredient']
            search_term = item.get('search_term', '')
            qty_needed = item['quantity_needed']
            if search_term and search_term.lower() != title.lower():
                tooltip = f'<span title="Searched on Rohlik as: {search_term}" style="cursor:help;font-size:0.8em;">ℹ️</span>'
            else:
                tooltip = ''

            st.markdown(
                f'#### {title} {tooltip} <span style="font-size:0.75em;color:grey;">(Need: {qty_needed})</span>',
                unsafe_allow_html=True,
            )
            
            options = item.get('options', [])
            if not options:
                st.warning("No alternatives found.")
                
                # Add a refetch button for single items
                if st.button(f"🔄 Refetch {item['ingredient']}", key=f"refetch_{i}"):
                    with st.spinner(f"Refetching {item['ingredient']}..."):
                        try:
                            fetch_arg = {"name": item["ingredient"], "quantity": item["quantity_needed"]}
                            new_data = fetch_item_from_rohlik(fetch_arg)
                            st.session_state.shopping_list[i] = new_data
                            st.session_state.selections[item['ingredient']] = 0
                            st.session_state.quantities.pop(item['ingredient'], None)
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
                current_idx = len(formatted_options) - 1  # Map -1 to SKIP_OPTION

            # Auto-populate quantity on first render for this ingredient
            ing_key = item['ingredient']
            if ing_key not in st.session_state.quantities:
                cur_opt = options[current_idx] if current_idx < len(options) else {}
                st.session_state.quantities[ing_key] = _auto_suggest_quantity(
                    item['quantity_needed'],
                    cur_opt.get('package_size', ''),
                    cur_opt.get('name', ''),
                )

            def on_change_selection(ing=ing_key, key=f"radio_{i}", opts=formatted_options, raw_opts=options, qty_needed=item['quantity_needed']):
                if key not in st.session_state:
                    return
                sel_str = st.session_state[key]
                if sel_str == SKIP_OPTION:
                    st.session_state.selections[ing] = -1
                    st.session_state.quantities[ing] = 1
                else:
                    try:
                        idx = opts.index(sel_str)
                        st.session_state.selections[ing] = idx
                        sel_opt = raw_opts[idx] if idx < len(raw_opts) else {}
                        st.session_state.quantities[ing] = _auto_suggest_quantity(
                            qty_needed,
                            sel_opt.get('package_size', ''),
                            sel_opt.get('name', ''),
                        )
                    except ValueError:
                        st.session_state.selections[ing] = 0

            st.radio(
                "Choose an option:",
                options=formatted_options,
                index=current_idx,
                key=f"radio_{i}",
                label_visibility="collapsed",
                on_change=on_change_selection
            )

            def on_change_qty(ing=ing_key, key=f"qty_{i}"):
                st.session_state.quantities[ing] = int(st.session_state[key])

            # Compute suggestion for the currently selected product (for display)
            cur_opt = options[current_idx] if current_idx < len(options) else {}
            suggested_qty = _auto_suggest_quantity(
                item['quantity_needed'],
                cur_opt.get('package_size', ''),
                cur_opt.get('name', ''),
            )

            col_qty, col_hint, _ = st.columns([1, 2, 4])
            with col_qty:
                st.number_input(
                    "Packs:",
                    min_value=1,
                    max_value=99,
                    value=int(st.session_state.quantities.get(ing_key, 1)),
                    step=1,
                    key=f"qty_{i}",
                    on_change=on_change_qty,
                )
            with col_hint:
                st.caption(f"Suggested: {suggested_qty} pack{'s' if suggested_qty != 1 else ''} for {item['quantity_needed']}")

            # Use search_term for the link if available
            search_name = item.get('search_term', item['ingredient'])
            encoded_ingredient = urllib.parse.quote(search_name + " ")
            search_url = f"https://www.rohlik.cz/en-CZ/hledat?q={encoded_ingredient}&companyId=1"
            st.markdown(f"[View on Rohlik]({search_url})")
            st.markdown("---")

def render_cart_summary_tab():
    st.subheader("🛒 Cart Summary")
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
        packs = int(st.session_state.quantities.get(ing, 1))

        final_selections.append({
            "ingredient": ing,
            "quantity_needed": item['quantity_needed'],
            "packs": packs,
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
                "quantity": packs
            })
            
    try:
        total_price = sum(
            float(str(sel.get('price', 0)).replace(',', '').replace('Kč', '').strip() or 0) * sel.get('packs', 1)
            for sel in final_selections
        )
    except Exception:
        total_price = 0.0
        
    st.markdown("#### Items to Buy")
    if final_selections:
        df_buy = pd.DataFrame(final_selections)
        st.table(df_buy[['ingredient', 'quantity_needed', 'packs', 'product_name', 'package_size', 'price', 'price_per_unit']])
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

    st.markdown("---")
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

                    out_path_json = ROOT / "final_selections.json"
                    with open(out_path_json, "w") as f:
                        json.dump(final_selections, f, indent=2, ensure_ascii=False)

                    st.balloons()
                except Exception as e:
                    st.error(f"A critical error occurred while adding items to the basket: {e}")

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
        tab1, tab2, tab3 = st.tabs(["📋 Pantry Match", "🔍 Rohlik Search", "🛒 Cart Summary"])
        
        with tab1:
            render_pantry_match_tab()
            
        with tab2:
            render_rohlik_search_tab()
            
        with tab3:
            render_cart_summary_tab()

if __name__ == "__main__":
    main()

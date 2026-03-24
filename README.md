# Rohlik Shopping Helper 🛒

A sophisticated, multi-agent personal shopping assistant for Rohlik.cz. It automates the process of extracting ingredients from recipe PDFs (like the NYT Cooking section), cross-referencing your home pantry, and sourcing the cheapest, high-quality alternatives directly from Rohlik.cz using a Model Context Protocol (MCP) browser bridge.

## Features
- **PDF Recipe Extraction**: Upload up to 10 recipe PDFs, and the system coordinates with Google's Gemini to parse them into structured ingredients.
- **Pantry Manifest Matching**: It checks your `pantry_manifest.md` configuration. If you already have "salt" or "butter", it asks you to confirm and securely skips buying duplicates.
- **Intelligent Sourcing**: Automatically finds top 3 alternative products on Rohlik.cz for your missing ingredients, preferring user-indicated brands (from `preferences.md`) and optimizing for price-to-weight value.
- **One-Click Carting**: Direct integration via MCP to add final selections straight to your active Rohlik.cz shopping cart!

---

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.10+
- A valid Rohlik.cz Account (Email & Password)
- Google Gemini API Key
- Node.js (for the MCP bridge `npx` runner)

### Initial Setup
1. **Clone the repository:**
   ```bash
   git clone https://github.com/USERNAME/rohlik_shopping_helper.git
   cd rohlik_shopping_helper
   ```

2. **Set up the Python Environment:**
   Run the following to initialize your virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   *(Note: You may need to create a `requirements.txt` from the active environment by running `pip freeze > requirements.txt` if not present.)*

3. **Configure Environment Variables:**
   Create a `.env` file in the root directory (never commit this to Git). It must contain:
   ```ini
   GEMINI_API_KEY="your-gemini-key"
   RHL_EMAIL="your.email@gmail.com"
   RHL_PASS="your-rohlik-password"
   ```

## 🚀 Usage Manual

1. **Configure Your Preferences**
   - Head over to `preferences.md` to type out any dietary restrictions, favored in-house brands, or items to strictly avoid.
   - Example: *"Always prefer Miil and Dacello brands. Never buy Albert Quality."*

2. **Update Your Pantry**
   - Keep a running list of your home inventory in `pantry_manifest.md`. Use a simple markdown list (e.g., `- Kosher Salt`, `- Olive Oil`).

3. **Start the Interface!**
   - Boot up the local Streamlit dashboard by running:
     ```bash
     streamlit run app.py
     ```
   - *If testing on a remote server, you may prefer: `streamlit run app.py --server.headless=true`*

4. **Follow the Steps in the App:**
   - **Upload**: Drop your NYT Cooking `.pdf` files into the uploader.
   - **Confirm Pantry**: The app will pause and ask if you truly have matched pantry items. 
   - **Source**: Click **"Find Products on Rohlik.cz"**. The assistant will securely bridge to Rohlik and search for items. *(Note: Please be patient, requests are staggered to prevent rate limiting).*
   - **Select and Checkout**: Choose your preferred alternatives and click **"Add to basket"**. The items will appear in your Rohlik.cz cart!

---

### Disclaimer
This is an automated scraping & bridging tool. Extensive concurrent use could trigger rate limits on Rohlik.cz. Use responsibly and adapt the `time.sleep()` delays in `app.py` if frequent timeouts occur.

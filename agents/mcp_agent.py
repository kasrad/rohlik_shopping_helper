import os
import json
from dotenv import load_dotenv
load_dotenv("/Users/radim/personal/rohlik_nyt_agent/.env")

from google.adk.agents import Agent
from google.adk.tools import McpToolset
from mcp import StdioServerParameters

class RohlikMCPAgent(Agent):
    """
    Agent that uses the Rohlik MCP Server to search for products.
    """
    def __init__(self, model="gemini-2.5-flash"):
        
        email = os.environ.get("RHL_EMAIL")
        password = os.environ.get("RHL_PASS")
        
        # Use absolute path to the stable npx we just installed
        npx_path = "/usr/local/bin/npx"
        
        params = StdioServerParameters(
            command=npx_path,
            args=[
                "-y", "mcp-remote",
                "https://mcp.rohlik.cz/mcp",
                "--header", f"rhl-email: {email}",
                "--header", f"rhl-pass: {password}"
            ]
        )

        mcp_toolset = McpToolset(connection_params=params)

        super().__init__(
            name="RohlikMCPAgent",
            instruction=(
                "You are an expert personal shopper for Rohlik.cz (Czech Republic). "
                "To find products, you MUST use the `batch_search_products` tool. "
                "IMPORTANT: You must provide keywords in CZECH (e.g., 'máslo' instead of 'butter'). "
                "User Preferences: Prioritize PRICE (cheapest quality options). "
                "Prefer in-house brands like 'Miil', 'Modrosladké', 'Pappudia', 'Ubomi', 'Dacello', 'FJORU', 'Kitchin', 'Yutto'. "
                "Do NOT prioritize Organic/BIO unless it is the cheapest option. "
                "Avoid Tesco Value and Albert Quality brands. "
                "Always return the 3 best options with prices and ensure the best price-to-quality ratio."
            ),
            tools=[mcp_toolset],
            model=model
        )

    def find_alternatives(self, ingredient: str) -> str:
        """Searches Rohlik for real product alternatives for an ingredient."""
        # Read preferences if available
        prefs = ""
        prefs_path = "/Users/radim/personal/rohlik_nyt_agent/preferences.md"
        if os.path.exists(prefs_path):
            with open(prefs_path, "r") as f:
                prefs = f.read()

        prompt = (
            f"Find 3 options for the ingredient: '{ingredient}'.\n\n"
            f"User Preferences:\n{prefs}\n"
            "Return EXACTLY a raw JSON array of 3 objects, without any markdown formatting wrappers like ```json. "
            "Each object MUST have the following keys:\n"
            "- name: (str) Exact name of the product\n"
            "- product_id: (int) The integer ID of the product (e.g. 1234567)\n"
            "- package_size: (str) The package size or weight (e.g., '250g', '1l', '1 ks')\n"
            "- price: (float) Price in CZK (just the number)\n"
            "- price_per_unit: (str) Price per unit (e.g., '219.60 Kč/kg' or 'N/A' if unavailable)\n"
            "- image_url: (str) The URL to the product's image (if available in the data, else an empty string)\n"
        )
        from google.adk import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types

        runner = Runner(agent=self, app_name="rohlik_nyt", session_service=InMemorySessionService(), auto_create_session=True)
        msg = types.Content(parts=[types.Part.from_text(text=prompt)])
        
        out = ""
        try:
            for event in runner.run(user_id="local", session_id="real_mcp_search", new_message=msg):
                if event.content and event.content.parts:
                    for p in event.content.parts:
                        if p.text:
                            out += p.text
        except Exception as e:
            print(f"Agent session run failed during find_alternatives: {e}")
            return []
        
        # Clean up markdown if the LLM adds it despite instructions
        out = out.strip()
        if out.startswith("```json"):
            out = out[7:-3].strip()
        elif out.startswith("```"):
            out = out[3:-3].strip()
            
        try:
            return json.loads(out)
        except Exception as e:
            print(f"Error parsing JSON from RohlikMCPAgent: {e}\nRaw output: {out}")
            return []

    def add_items_to_basket(self, items: list[dict]) -> str:
        """
        Adds a list of items to the Rohlik cart via the MCP tool.
        Expects items in format: [{'productId': 1234567, 'quantity': 1}, ...]
        """
        prompt = (
            "Add the following items to my Rohlik shopping basket using the `add_items_to_cart` tool exactly as listed:\n"
            f"{json.dumps(items, indent=2)}\n"
            "Respond with a success message once added."
        )
        
        from google.adk import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types

        runner = Runner(agent=self, app_name="rohlik_nyt", session_service=InMemorySessionService(), auto_create_session=True)
        msg = types.Content(parts=[types.Part.from_text(text=prompt)])
        
        out = ""
        try:
            for event in runner.run(user_id="local", session_id="real_mcp_cart", new_message=msg):
                if event.content and event.content.parts:
                    for p in event.content.parts:
                        if p.text:
                            out += p.text
        except Exception as e:
            err_msg = f"Agent session run failed during add_items_to_basket: {e}"
            print(err_msg)
            return err_msg
            
        return out

if __name__ == "__main__":
    agent = RohlikMCPAgent()
    print("--- Rohlik MCP Real Search JSON Test ---")
    result = agent.find_alternatives("máslo")
    print(json.dumps(result, indent=2))

import os
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

class CartAgent(Agent):
    """
    Agent responsible for taking approved ingredients and adding them
    to the Rohlik.cz shopping cart via the MCP server.
    """
    def __init__(self, model="gemini-2.5-flash"):
        
        cart_tool = FunctionTool(func=self._add_to_cart)


        super().__init__(
            name="CartAgent",
            instruction=(
                "You are an expert at managing shopping carts. "
                "Given a list of approved products with their specific selection or IDs, "
                "use your tool to add each item to the user's Rohlik cart."
            ),
            tools=[cart_tool],
            model=model
        )

    def _add_to_cart(self, product_identifier: str, quantity: int = 1) -> str:
        """Adds a specific product ID or name to the active Rohlik cart."""
        # Mocking the MCP cart interaction
        print(f"[Cart Agent] Action: Added {quantity}x of {product_identifier} to cart.")
        return f"Successfully added {quantity} of {product_identifier} to the cart."

    def ingest_shopping_list(self, approved_items: list) -> str:
        prompt = f"Add the following items to the cart, one by one: {approved_items}"
        
        from google.adk import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types

        runner = Runner(agent=self, app_name="rohlik_nyt", session_service=InMemorySessionService(), auto_create_session=True)
        msg = types.Content(parts=[types.Part.from_text(text=prompt)])
        
        out = ""
        for event in runner.run(user_id="local", session_id="s1", new_message=msg):
            if event.content and event.content.parts:
                for p in event.content.parts:
                    if p.text:
                        out += p.text
        return out

import os
import json
import re
import asyncio
from dotenv import load_dotenv
import anthropic
from mcp import StdioServerParameters, ClientSession
from mcp.client.stdio import stdio_client

from config import ENV_PATH, PREFERENCES_PATH, NPX_PATH

load_dotenv(ENV_PATH, override=True)


class RohlikMCPAgent:
    """
    Agent that uses the Rohlik MCP Server to search for products.
    Uses Claude via the Anthropic SDK with a manual MCP agentic loop.
    """

    def __init__(self, model="claude-haiku-4-5-20251001", prefs_path=PREFERENCES_PATH):
        self.model = model
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        email = os.environ.get("RHL_EMAIL")
        password = os.environ.get("RHL_PASS")

        self.server_params = StdioServerParameters(
            command=NPX_PATH,
            args=[
                "-y", "mcp-remote",
                "https://mcp.rohlik.cz/mcp",
                "--header", f"rhl-email: {email}",
                "--header", f"rhl-pass: {password}",
            ]
        )

        prefs = ""
        if os.path.exists(prefs_path):
            with open(prefs_path, "r") as f:
                prefs = f.read()

        self.instruction = (
            "You are an expert personal shopper for Rohlik.cz (Czech Republic). "
            "To find products, you MUST use the `batch_search_products` tool. "
            "IMPORTANT: You must provide keywords in CZECH (e.g., 'máslo' instead of 'butter'). "
            "Always return the 3 best options with prices and ensure the best price-to-quality ratio.\n\n"
            f"User preferences:\n{prefs}"
        )

    async def _run_agent(self, prompt: str, max_tokens: int = 8096) -> str:
        """Runs an agentic loop: connects to Rohlik MCP, passes tools to Claude."""
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Discover tools from the MCP server
                tools_result = await session.list_tools()
                tools = [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema,
                    }
                    for tool in tools_result.tools
                ]

                messages = [{"role": "user", "content": prompt}]

                while True:
                    # Run the synchronous Anthropic call in a thread so the
                    # asyncio event loop stays free to service MCP keepalives.
                    response = await asyncio.to_thread(
                        self.client.messages.create,
                        model=self.model,
                        max_tokens=max_tokens,
                        system=self.instruction,
                        tools=tools,
                        messages=messages,
                    )

                    if response.stop_reason == "end_turn":
                        text_parts = [b.text for b in response.content if hasattr(b, "text")]
                        return "\n".join(text_parts)

                    if response.stop_reason == "tool_use":
                        messages.append({"role": "assistant", "content": response.content})

                        tool_results = []
                        for block in response.content:
                            if block.type != "tool_use":
                                continue
                            try:
                                result = await session.call_tool(block.name, block.input)
                                content_parts = [
                                    c.text if hasattr(c, "text") else str(c)
                                    for c in result.content
                                ]
                                content = "\n".join(content_parts)
                            except Exception as e:
                                content = f"Tool error: {e}"

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": content,
                            })

                        messages.append({"role": "user", "content": tool_results})
                    else:
                        # Unexpected stop reason — return whatever text we have
                        text_parts = [b.text for b in response.content if hasattr(b, "text")]
                        return "\n".join(text_parts)

    def _run(self, prompt: str, max_tokens: int = 8096) -> str:
        """Bridge async _run_agent to a synchronous call."""
        return asyncio.run(self._run_agent(prompt, max_tokens=max_tokens))

    def find_alternatives(self, ingredient: str) -> list:
        """Searches Rohlik for real product alternatives for an ingredient."""
        prompt = (
            f"Find 3 options for the ingredient: '{ingredient}'.\n\n"
            "Return EXACTLY a raw JSON array of 3 objects, without any markdown formatting wrappers like ```json. "
            "Each object MUST have the following keys:\n"
            "- name: (str) Exact name of the product\n"
            "- product_id: (int) The integer ID of the product (e.g. 1234567)\n"
            "- package_size: (str) The package size or weight (e.g., '250g', '1l', '1 ks')\n"
            "- price: (float) Price in CZK (just the number)\n"
            "- price_per_unit: (str) Price per unit (e.g., '219.60 Kč/kg' or 'N/A' if unavailable)\n"
            "- image_url: (str) The URL to the product's image (if available in the data, else an empty string)\n"
        )

        try:
            out = self._run(prompt)
        except Exception as e:
            print(f"Agent run failed during find_alternatives: {e}")
            return []

        out = out.strip()
        if out.startswith("```json"):
            out = out[7:].rstrip("`").strip()
        elif out.startswith("```"):
            out = out[3:].rstrip("`").strip()

        try:
            return json.loads(out)
        except Exception as e:
            print(f"Error parsing JSON from RohlikMCPAgent: {e}\nRaw output: {out}")
            return []

    def find_alternatives_batch(self, ingredients: list[str]) -> dict[str, list]:
        """
        Searches Rohlik for product alternatives for all ingredients in a single
        agent session, instead of spawning one session per ingredient.

        Args:
            ingredients: List of search terms (already translated to Czech).

        Returns:
            Dict mapping each search term to a list of product alternative dicts.
            Missing or failed ingredients map to an empty list.
        """
        if not ingredients:
            return {}

        ingredient_list = "\n".join(f"- {ing}" for ing in ingredients)
        prompt = (
            f"Find 3 product options for EACH of the following {len(ingredients)} ingredients "
            f"using batch_search_products:\n{ingredient_list}\n\n"
            "Return EXACTLY a raw JSON object with NO markdown wrappers. "
            "Keys must be the ingredient names exactly as listed above. "
            "Each value is an array of up to 3 product objects, each with keys:\n"
            "- name: (str) exact product name\n"
            "- product_id: (int) integer product ID\n"
            "- package_size: (str) e.g. '250g', '1l', '1 ks'\n"
            "- price: (float) price in CZK\n"
            "- price_per_unit: (str) e.g. '219.60 Kč/kg' or 'N/A'\n"
            "- image_url: (str) product image URL or empty string\n"
            "If no results found for an ingredient, use an empty array []."
        )

        try:
            out = self._run(prompt, max_tokens=16000)
        except Exception as e:
            print(f"Batch agent run failed: {e}")
            return {ing: [] for ing in ingredients}

        out = out.strip()

        # Strip markdown code fences if present
        if out.startswith("```json"):
            out = out[7:].rstrip("`").strip()
        elif out.startswith("```"):
            out = out[3:].rstrip("`").strip()

        # Direct parse
        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            # Claude may have added prose before/after the JSON block —
            # find the outermost {...} in the response
            match = re.search(r'\{.*\}', out, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    print(f"Error parsing batch JSON\nRaw output: {out[:500]}")
                    return {ing: [] for ing in ingredients}
            else:
                print(f"No JSON object found in batch response\nRaw output: {out[:500]}")
                return {ing: [] for ing in ingredients}

        # Ensure all ingredients have an entry even if Claude missed some
        for ing in ingredients:
            if ing not in result:
                print(f"Warning: batch result missing ingredient '{ing}'")
                result[ing] = []
        return result

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

        try:
            return self._run(prompt)
        except Exception as e:
            err_msg = f"Agent run failed during add_items_to_basket: {e}"
            print(err_msg)
            return err_msg


if __name__ == "__main__":
    agent = RohlikMCPAgent()
    print("--- Rohlik MCP Claude Search Test ---")
    result = agent.find_alternatives("máslo")
    print(json.dumps(result, indent=2, ensure_ascii=False))

import os
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from .browser_agent import NYTBrowserAgent
from .mcp_agent import RohlikMCPAgent

class CoordinatorAgent(Agent):
    """
    Agent responsible for coordinating the workflow:
    1. Triggers BrowserAgent to get ingredients.
    2. Filters against pantry_manifest.md.
    3. Triggers MCPAgent to find alternatives for missing items.
    """
    def __init__(self, model="gemini-2.5-flash"):
        
        browser_agent = NYTBrowserAgent()
        mcp_agent = RohlikMCPAgent()

        extract_tool = FunctionTool(func=browser_agent.extract_ingredients)
        mcp_search_tool = FunctionTool(func=mcp_agent.find_alternatives)

        super().__init__(
            name="CoordinatorAgent",
            instruction=(
                "You are the master coordinator for a multi-agent grocery shopping pipeline. "
                "Step 1: Given a NYT Cooking URL, use the extract_nyt tool to get the raw ingredient list. "
                "Step 2: Read 'pantry_manifest.md' and filter out the items the user already has. "
                "Step 3: For the remaining missing items, use find_rohlik_alternatives to retrieve exactly 3 options for each. "
                "Step 4: Format the final output as a structured JSON array representing the missing ingredients "
                "and their 3 options with prices."
            ),
            tools=[extract_tool, mcp_search_tool],
            model=model
        )

    def process_url(self, url: str) -> str:
        # Read pantry manifest locally to inject into prompt
        pantry_contents = "No pantry items defined."
        try:
            if os.path.exists("pantry_manifest.md"):
                with open("pantry_manifest.md", "r") as f:
                    pantry_contents = f.read()
        except Exception as e:
            print(f"Warning: Could not read pantry_manifest.md: {e}")

        prompt = (
            f"Process this NYT Cooking URL: {url}\n\n"
            f"Here is the contents of the user's pantry:\n"
            f"---\n{pantry_contents}\n---\n"
            f"Do not ask the user for the pantry file. Filter out the ingredients listed above from the recipe "
            f"before calling the mcp_search_tool for the missing items."
        )
        
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

import os
import pypdf
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

def read_local_pdf(url: str = "") -> str:
    """Reads the local cake_recipe.pdf instead of doing any web scraping."""
    pdf_path = os.path.join(os.path.dirname(__file__), "cake_recipe.pdf")
    try:
        text = ""
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        print(f"Read {len(text)} characters from {pdf_path}")
        return text
    except Exception as e:
        return f"Failed to read PDF {pdf_path}: {e}"

class NYTBrowserAgent(Agent):
    """
    An agent specialized in reading a local PDF file for testing recipe parsing.
    """
    def __init__(self, model="gemini-2.5-flash"):
        pdf_tool = FunctionTool(func=read_local_pdf)
        
        super().__init__(
            name="NYTBrowserAgent",
            instruction=(
                "You are an expert at extracting recipe ingredients from provided text. "
                "Your task is to use the read_local_pdf tool (ignore the url parameter), "
                "and return EXACTLY the markdown list of ingredients with no extra commentary."
            ),
            tools=[pdf_tool],
            model=model
        )

    def extract_ingredients(self, nyt_url: str) -> str:
        """Extracts ingredients from the local PDF regardless of the URL passed in."""
        prompt = f"Extract the ingredients from the local recipe PDF."
        
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

"""
Optional tool adapters for the assistant (e.g. web search). Not used in the first version.
When adding web search: implement a tool that takes a query and returns a string; register it
here and call it from services.py only when needed, without hard-coding in views.
"""
# Example future API:
# def get_tools(): return [WebSearchTool()]  # noqa: E800
# def run_tool(name: str, params: dict) -> str: ...  # noqa: E800

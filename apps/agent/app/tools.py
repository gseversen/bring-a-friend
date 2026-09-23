"""Fake research tools. They return canned data after a short delay so the
live timeline has something to show without calling real services."""

import asyncio

TOOL_DELAY_S = 0.8

TOOLS = [
    {
        "name": "search_web",
        "description": "Search the web. Returns a list of result titles and URLs.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_page",
        "description": "Read the text content of a web page by URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "save_note",
        "description": "Save a short research note for the final answer.",
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
    },
]


def slugify(text: str) -> str:
    return "-".join(text.lower().split())[:40]


async def run_tool(name: str, args: dict) -> str:
    await asyncio.sleep(TOOL_DELAY_S)
    if name == "search_web":
        slug = slugify(args["query"])
        return "\n".join(
            f"{i}. {title} - https://example.com/{slug}/{i}"
            for i, title in enumerate(["Overview", "Recent developments", "Expert opinions"], 1)
        )
    if name == "read_page":
        return (
            f"Content of {args['url']}: This page summarizes the topic, lists three key "
            "facts, and notes that experts disagree on long-term impact."
        )
    if name == "save_note":
        return f"Saved note ({len(args['note'])} chars)."
    raise ValueError(f"Unknown tool: {name}")

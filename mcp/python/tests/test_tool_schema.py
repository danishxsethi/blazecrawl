import asyncio

from blazecrawl_mcp.server import list_tools

EXPECTED_TOOLS = [
    {
        "name": "scrape",
        "description": "Scrape a URL and return clean Markdown (LLM-ready).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http/https URL to scrape"},
                "render": {
                    "type": "string",
                    "description": "Rendering mode: auto-select, static HTTP, or browser rendering",
                    "enum": ["auto", "static", "browser"],
                    "default": "auto",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "map",
        "description": "Discover the URL set of a site (sitemap + link graph).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "http/https site URL whose discoverable links should be mapped",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "crawl",
        "description": "Crawl a site (BFS, same-origin) and return page Markdown.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http/https site URL to crawl"},
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum number of pages to return from the crawl",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum same-origin link depth from the starting URL",
                },
            },
            "required": ["url"],
        },
    },
]


def test_python_mcp_tool_schema_snapshot() -> None:
    tools = asyncio.run(list_tools())
    exposed = [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.inputSchema,
        }
        for tool in tools
    ]
    assert exposed == EXPECTED_TOOLS

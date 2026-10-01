#!/usr/bin/env python3
"""Minimal, standards-compliant MCP stdio client used ONLY to generate the README
MCP demo. It performs a real MCP exchange against a real blazecrawl-mcp server:

    initialize -> tools/list -> tools/call (scrape)

No LLM is involved or implied. The output printed is the real server's response.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from mcp import ClientSession, StdioServerParameters


async def main() -> int:
    server = StdioServerParameters(
        command=sys.argv[1] if len(sys.argv) > 1 else "blazecrawl-mcp",
        args=[],
        env={
            "PATH": os.environ.get("PATH", ""),
            "BLAZECRAWL_API_URL": os.environ.get("BLAZECRAWL_API_URL", "http://127.0.0.1:8010"),
            "BLAZECRAWL_API_KEY": os.environ.get("BLAZECRAWL_API_KEY", ""),
        },
    )
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print("tools/list ->", ", ".join(names))

        result = await session.call_tool(
            "scrape", {"url": "https://example.com", "render": "static"}
        )
        if result.isError or not result.content or not isinstance(result.content[0], TextContent):
            raise RuntimeError(f"MCP scrape failed: {result}")
        text = result.content[0].text
        print("tools/call scrape ->")
        print(text.split("\n\n", 1)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

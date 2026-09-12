"""Shape used by modelcontextprotocol/servers `fetch`: low-level Server,
literal name, inline JSON Schema."""

from mcp.server import Server
from mcp.types import Tool

server = Server("mcp-fetch")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch",
            description="Fetches a URL and extracts its contents as markdown.",
            inputSchema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )
    ]

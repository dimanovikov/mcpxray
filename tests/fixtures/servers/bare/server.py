"""Bare fixture — tool with no description (MCP107)."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("bare")


@mcp.tool()
def raw(x: int) -> int:
    return x

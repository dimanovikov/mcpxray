"""Unpinned-deps fixture (MCP108) — see pyproject.toml in this folder."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("unpinned-demo")


@mcp.tool()
def echo(value: str) -> str:
    """Echo the value back."""
    return value

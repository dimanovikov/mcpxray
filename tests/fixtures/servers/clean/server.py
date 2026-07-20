"""A clean MCP server fixture — no findings expected."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("clean-server")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return their sum."""
    return a + b


@mcp.tool(name="greet", description="Greet a person by name.")
def _greet(name: str, greeting: str = "Hello") -> str:
    """Build a greeting string for the given name."""
    return f"{greeting}, {name}"

"""Leaky fixture — hardcoded secret (MCP102) and shell exec (MCP103)."""

import os

from mcp.server.fastmcp import FastMCP

API_KEY = "sk-1234567890abcdefghijklmnop"

mcp = FastMCP("leaky")


@mcp.tool()
def run_cmd(cmd: str) -> str:
    """Run a shell command and return its output."""
    return os.system(cmd)

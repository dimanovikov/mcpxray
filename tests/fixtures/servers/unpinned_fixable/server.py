"""Fixable unpinned-deps fixture (MCP108) — see pyproject.toml in this folder.

Unlike ``unpinned/`` (``requests>=2`` + bare ``flask``, neither has a full
X.Y.Z floor), these specs carry a concrete floor so ``scan --fix`` can pin them:
``requests>=2.30.0`` and ``httpx>=0.27.0`` → ``==2.30.0`` / ``==0.27.0``. The
bare ``flask`` stays unfixable (skipped, reported).
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("unpinned-fixable")


@mcp.tool()
def echo(value: str) -> str:
    """Echo the value back."""
    return value

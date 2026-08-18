"""mcpxray — static linter + 0-100 scorecard for MCP servers."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcpxray")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"

# The top-level package surface is intentionally tiny (just the version). The
# stable plugin API lives at its submodule paths — see CONTRIBUTING.md →
# "Plugin API stability" for the full contract.
__all__ = ["__version__"]

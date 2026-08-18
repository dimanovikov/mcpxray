"""mcpxray — static linter + 0-100 scorecard for MCP servers."""

from importlib.metadata import PackageNotFoundError, version

# The installed distribution is `mcpxray-cli` (the PyPI name; `mcpxray` is
# taken there by an unrelated project) — the import package is `mcpxray`.
try:
    __version__ = version("mcpxray-cli")
except PackageNotFoundError:
    try:
        __version__ = version("mcpxray")  # pre-rename installs
    except PackageNotFoundError:  # source tree that isn't installed
        __version__ = "0.0.0"

# The top-level package surface is intentionally tiny (just the version). The
# stable plugin API lives at its submodule paths — see CONTRIBUTING.md →
# "Plugin API stability" for the full contract.
__all__ = ["__version__"]

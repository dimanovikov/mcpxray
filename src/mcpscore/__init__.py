"""mcpscore — static linter + 0-100 scorecard for MCP servers."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcpscore")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"

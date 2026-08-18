"""Extractors turn a path (source tree or manifest) into a :class:`McpServer` IR."""

from __future__ import annotations

# Importing the builtin extractors triggers @register_extractor self-registration.
from mcpxray.extract import manifest as _manifest  # noqa: F401
from mcpxray.extract import python_static as _python_static  # noqa: F401
from mcpxray.extract import typescript_static as _typescript_static  # noqa: F401
from mcpxray.extract.base import (
    Extractor,
    extractor_for,
    extractors,
    register_extractor,
)

__all__ = ["Extractor", "extractor_for", "extractors", "register_extractor"]

"""Extractor API + registry.

An :class:`Extractor` reads a path (a source tree or a manifest file) and emits
a :class:`~mcpscore.ir.McpServer`. Builtins self-register via
:func:`register_extractor`; external packages declare an entry-point in the
``mcpscore.extractors`` group (loaded in v0.1 alongside rule entry-points).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from mcpscore.ir import McpServer

# Stable plugin API for extractor authors (see CONTRIBUTING.md → "Plugin API
# stability"). ``_EXTRACTORS`` and any ``_``-prefixed name are internal.
__all__ = ["Extractor", "register_extractor", "extractors", "extractor_for"]

_EXTRACTORS: list[type[Extractor]] = []


class Extractor(ABC):
    """Base class for all extractors."""

    language: str = ""  # "python" | "typescript" | "" (manifest)

    @abstractmethod
    def applies_to(self, path: Path) -> bool:
        """True if this extractor can read ``path`` (file or directory)."""

    @abstractmethod
    def extract(self, path: Path, *, root: Path | None = None) -> McpServer:
        """Build a :class:`McpServer` from ``path``.

        ``path`` is the *scan scope* — the tree walked for source files. ``root``,
        when given, is the wider *project root* to read ``pyproject.toml`` /
        lockfiles from (it differs from ``path`` only when the caller has narrowed
        the scan to a subpackage). Defaults to ``path`` so unscoped calls behave
        exactly as before.
        """


def register_extractor(cls: type[Extractor]) -> type[Extractor]:
    """Class decorator: register an :class:`Extractor` subclass."""
    _EXTRACTORS.append(cls)
    return cls


def extractors() -> list[type[Extractor]]:
    """All registered extractor classes (builtins first, registration order)."""
    return list(_EXTRACTORS)


def extractor_for(path: Path) -> Extractor | None:
    """Return the first registered extractor whose ``applies_to`` matches."""
    for cls in _EXTRACTORS:
        ext = cls()
        if ext.applies_to(path):
            return ext
    return None

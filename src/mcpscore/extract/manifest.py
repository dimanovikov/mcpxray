"""Manifest extractor — parse a captured ``tools/list`` JSON dump.

For servers whose source we can't (or don't want to) parse — any language,
compiled, or third-party — a user captures ``tools/list`` and feeds the JSON
here. Tools learned this way carry ``runtime_only=True``.

The per-tool construction (:func:`_tool_from_entry`) and the
:class:`~mcpscore.ir.McpServer` assembly (:func:`_build`) are shared with the
runtime capture path (:mod:`mcpscore.runtime` → :func:`from_tools`), so a
hand-fed manifest file and a live ``tools/list`` capture produce the same IR.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcpscore.extract.base import Extractor, register_extractor
from mcpscore.ir import SOURCE_MANIFEST, SOURCE_RUNTIME, McpServer, ServerMeta, Tool


def _find_tools(payload: object) -> list[dict]:
    """Locate the tools list in either a raw or JSON-RPC-wrapped response."""
    if isinstance(payload, dict):
        if isinstance(payload.get("tools"), list):
            return payload["tools"]
        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            return result["tools"]
    return []


def _looks_like_manifest(path: Path) -> bool:
    if not path.is_file() or path.suffix != ".json":
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(_find_tools(payload))


def _tool_from_entry(entry: object) -> Tool | None:
    """Build a single ``runtime_only`` tool from a tools/list entry, or skip it."""
    if not isinstance(entry, dict) or not entry.get("name"):
        return None
    return Tool(
        name=entry["name"],
        description=entry.get("description"),
        input_schema=entry.get("inputSchema") or entry.get("input_schema") or {},
        runtime_only=True,
    )


def _build(
    tools: list[dict],
    *,
    name: str,
    path_str: str,
    version: str | None = None,
    source_mode: str = SOURCE_MANIFEST,
) -> McpServer:
    """Assemble a runtime-only :class:`McpServer` from a tools/list list."""
    server = McpServer(
        meta=ServerMeta(name=name, version=version, language=None, path=path_str),
        source_mode=source_mode,
    )
    for entry in tools:
        tool = _tool_from_entry(entry)
        if tool is not None:
            server.tools.append(tool)
    return server


def from_tools(
    tools: list[dict],
    *,
    name: str = "runtime",
    path_str: str = "<runtime>",
    version: str | None = None,
) -> McpServer:
    """Build an IR from a captured ``tools/list`` tool list (runtime path)."""
    return _build(tools, name=name, path_str=path_str, version=version, source_mode=SOURCE_RUNTIME)


@register_extractor
class ManifestExtractor(Extractor):
    """Extract tools from a captured ``tools/list`` JSON dump."""

    language = ""  # language-agnostic

    def applies_to(self, path: Path) -> bool:
        return _looks_like_manifest(path)

    def extract(self, path: Path, *, root: Path | None = None) -> McpServer:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _build(_find_tools(payload), name=path.stem, path_str=str(path))

"""Intermediate representation for an MCP server under analysis.

Every extractor emits a :class:`McpServer`; every rule consumes one. The IR is
extractor-agnostic — it models the union of what static source parsing and a
``tools/list`` manifest can tell us, with provenance (``location``) so findings
point back to real source lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Public, stable surface for this module. Names listed here are the plugin API
# (see CONTRIBUTING.md → "Plugin API stability"); everything else — including
# ``_SEVERITY_RANK`` and ``RISK_WEIGHT`` — is internal and may change at any
# release. ``from mcpscore.ir import *`` yields exactly this list.
__all__ = [
    # severities
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    # risk tiers
    "RISK_CRITICAL",
    "RISK_HIGH",
    "RISK_MEDIUM",
    "RISK_LOW",
    # scoring
    "ERROR_SCORE_CAP",
    # how the IR was obtained
    "SOURCE_STATIC",
    "SOURCE_MANIFEST",
    "SOURCE_RUNTIME",
    # helpers
    "severity_rank",
    # dataclasses
    "Diagnostic",
    "Tool",
    "Resource",
    "Prompt",
    "ServerMeta",
    "McpServer",
]

# --- severities --------------------------------------------------------------
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
_SEVERITY_RANK = {SEVERITY_ERROR: 3, SEVERITY_WARNING: 2, SEVERITY_INFO: 1}

# --- risk tiers (drive score weighting, mirroring OpenSSF Scorecard) ---------
# Higher weight = a failing check drags the score down harder.
RISK_CRITICAL = "critical"
RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"
RISK_WEIGHT = {
    RISK_CRITICAL: 10,
    RISK_HIGH: 5,
    RISK_MEDIUM: 2,
    RISK_LOW: 1,
}

# A score ceiling applied whenever any ERROR-severity finding exists, so a single
# critical bug can't be diluted to a green score by clean tooling elsewhere.
ERROR_SCORE_CAP = 60

SOURCE_STATIC = "static"
SOURCE_MANIFEST = "manifest"
SOURCE_RUNTIME = "runtime"  # tools captured by spawning the server (tools/list)


def severity_rank(sev: str) -> int:
    """Higher = more severe. Unknown severities rank below INFO."""
    return _SEVERITY_RANK.get(sev, 0)


@dataclass
class Diagnostic:
    """A single lint finding. Stable ``rule_id``; ``line``/``col`` are 1-indexed."""

    rule_id: str
    severity: str
    message: str
    tool: str | None = None  # name of the offending tool, if any
    file: str | None = None
    line: int | None = None
    col: int | None = None


@dataclass
class Tool:
    """An MCP tool: name + LLM-visible description + JSON Schema for its inputs."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None  # file the tool was declared in
    line: int | None = None  # 1-indexed line of the declaration
    runtime_only: bool = False  # True when learned from a manifest, not source
    # Destructured handler parameter names, for MCP105 (schema/impl drift).
    # ``None`` = undeterminable (bare ``args`` identifier, Python, or a manifest
    # tool with no source handler) → the rule can't compare and skips.
    # ``[]``   = the handler explicitly takes no params (``()``).
    # ``[...]``= the names a destructured ``{a, b}`` handler actually reads.
    handler_params: list[str] | None = None


@dataclass
class Resource:
    """An MCP resource (``resources/list``). Analyzed in v0.2."""

    uri: str
    name: str | None = None
    description: str | None = None
    mime_type: str | None = None


@dataclass
class Prompt:
    """An MCP prompt template (``prompts/list``). Analyzed in v0.2."""

    name: str
    description: str | None = None


@dataclass
class ServerMeta:
    """Identity metadata for the server under analysis. All optional."""

    name: str | None = None
    version: str | None = None
    language: str | None = None  # "python" | "typescript" | None
    path: str | None = None  # root path analyzed
    repo: str | None = None  # optional repo URL


@dataclass
class McpServer:
    """The universal IR for an MCP server. Extractors emit it; rules read it."""

    meta: ServerMeta
    tools: list[Tool] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    prompts: list[Prompt] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)  # name -> spec
    sources: dict[str, str] = field(default_factory=dict)  # source_path -> text
    lockfiles: list[str] = field(default_factory=list)  # lockfile basenames found
    diagnostics: list[Diagnostic] = field(default_factory=list)
    source_mode: str = SOURCE_STATIC  # how the IR was obtained

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == SEVERITY_ERROR]

    @property
    def has_errors(self) -> bool:
        return any(d.severity == SEVERITY_ERROR for d in self.diagnostics)

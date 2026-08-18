"""Verdict engine — collapse findings into a plain-language safety verdict.

A consumer just wants to know "can I install this MCP server?" — not a raw
``82/100 (B)``. :func:`verdict` projects a :class:`~mcpxray.ir.McpServer`
(plus its :class:`~mcpxray.score.ScoreResult`) onto a traffic-light tier with a
human headline, an actionable recommendation, and the top reasons. It is a pure
downstream view: it changes neither the score nor the rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mcpxray.ir import SEVERITY_WARNING, SOURCE_STATIC

if TYPE_CHECKING:
    from mcpxray.ir import Diagnostic, McpServer
    from mcpxray.score import ScoreResult

# --- tiers -------------------------------------------------------------------
TIER_OK = "ok"
TIER_CAUTION = "caution"
TIER_DANGER = "danger"
TIER_UNKNOWN = "unknown"
TIERS = (TIER_OK, TIER_CAUTION, TIER_DANGER, TIER_UNKNOWN)

# rule_id -> one short, plain-language phrase shown to the user.
_RULE_PHRASE = {
    "MCP101": "Possible tool-poisoning in a tool description",
    "MCP102": "Leaked secrets/keys in source",
    "MCP103": "Dangerous code execution (eval/exec/shell)",
    "MCP104": "Weak or empty input schemas",
    "MCP105": "Schema/handler drift (declared vs actual params)",
    "MCP106": "JSON-Schema incompatibilities (may break Cursor/ChatGPT)",
    "MCP107": "Tool descriptions need cleanup",
    "MCP108": "Unpinned dependencies (supply-chain risk)",
    "MCP109": "Insecure network transport (no TLS/auth)",
}

# Display order for reasons: scariest first so the top of the card leads with
# RCE / secrets / poisoning rather than a hygiene warning.
_RULE_PRIORITY = {
    "MCP103": 0,
    "MCP102": 1,
    "MCP101": 2,
    "MCP108": 3,
    "MCP104": 4,
    "MCP106": 5,
    "MCP107": 6,
    "MCP105": 7,
    "MCP109": 8,
}

_MAX_REASONS = 5


@dataclass(frozen=True)
class Reason:
    """One line of the 'Why' block: a rule, its plain phrase, and its count."""

    rule_id: str
    phrase: str
    count: int


@dataclass(frozen=True)
class Verdict:
    """The consumer-facing outcome of checking a server."""

    tier: str
    headline: str
    recommendation: str
    reasons: list[Reason] = field(default_factory=list)


def _reasons(diags: list[Diagnostic]) -> list[Reason]:
    """Group diagnostics by rule_id, order scariest-first, cap at ``_MAX_REASONS``."""
    counts: dict[str, int] = {}
    for d in diags:
        counts[d.rule_id] = counts.get(d.rule_id, 0) + 1
    ordered = sorted(counts, key=lambda r: (_RULE_PRIORITY.get(r, 99), r))
    return [
        Reason(rule_id=r, phrase=_RULE_PHRASE.get(r, r), count=counts[r])
        for r in ordered[:_MAX_REASONS]
    ]


def verdict(doc: McpServer, score_result: ScoreResult | None = None) -> Verdict:  # noqa: ARG001
    """Project a server onto a consumer-facing :class:`Verdict`.

    Tier rules (checked in order):

    * **unknown** — static source with zero tools extracted (a language mcpxray
      doesn't parse, or a tree with no tool registrations). A manifest/runtime
      capture with zero tools is *not* unknown: the user handed it to us
      deliberately, so "couldn't check" would be misleading.
    * **danger** — any ERROR-severity finding (poisoning / secrets / RCE).
    * **caution** — no errors, but at least one WARNING.
    * **ok** — nothing found.
    """
    if doc.source_mode == SOURCE_STATIC and not doc.tools:
        return Verdict(
            tier=TIER_UNKNOWN,
            headline="Couldn't verify statically",
            recommendation=(
                "Couldn't verify statically; review manually, capture the server's "
                "tools/list and re-run with --manifest, or use --runtime --command "
                "to let mcpxray capture it live."
            ),
        )

    if doc.has_errors:
        return Verdict(
            tier=TIER_DANGER,
            headline="Do not install this server",
            recommendation=(
                "This server has critical issues; do not install it. "
                "Fix the issues above or pick a different server."
            ),
            reasons=_reasons(doc.errors),
        )

    warnings = [d for d in doc.diagnostics if d.severity == SEVERITY_WARNING]
    if warnings:
        reasons = _reasons(warnings)
        top = ", ".join(r.phrase for r in reasons[:3])
        return Verdict(
            tier=TIER_CAUTION,
            headline="Use with caution",
            recommendation=f"Usable, but be aware of: {top}.",
            reasons=reasons,
        )

    return Verdict(
        tier=TIER_OK,
        headline="Looks clean",
        recommendation="Looks clean, safe to add to Claude Code.",
    )

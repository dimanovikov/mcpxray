"""Consumer-facing verdict card — a traffic-light summary, not a raw score.

``render`` shares the standard formatter signature so ``mcpxray scan -f card``
works for free; ``render_verdict`` is the richer entry point the ``check``
command uses (it already holds a :class:`~mcpxray.verdict.Verdict` and wants
``--details`` control).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from mcpxray.ir import SOURCE_RUNTIME
from mcpxray.report import plain as plain_fmt
from mcpxray.verdict import TIER_CAUTION, TIER_DANGER, TIER_OK, TIER_UNKNOWN, Verdict, verdict

if TYPE_CHECKING:
    from mcpxray.ir import Diagnostic, McpServer
    from mcpxray.score import ScoreResult

# (emoji, ascii tag) per tier. The tag embeds the label so the ASCII fallback
# reads "[DANGER]" while the emoji form renders "🔴 DANGER".
_GLYPHS = {
    TIER_OK: ("🟢", "[OK]"),
    TIER_CAUTION: ("🟡", "[CAUTION]"),
    TIER_DANGER: ("🔴", "[DANGER]"),
    TIER_UNKNOWN: ("⚪", "[?]"),
}


def _supports_unicode() -> bool:
    """True when stdout can render emoji/bullets. Monkeypatchable in tests."""
    enc = (sys.stdout.encoding or "").lower().replace("-", "").replace("_", "")
    return "utf8" in enc


def _header(v: Verdict) -> str:
    emoji, tag = _GLYPHS[v.tier]
    return f"{emoji} {v.tier.upper()}" if _supports_unicode() else tag


def _bullet() -> str:
    return "•" if _supports_unicode() else "-"


def _times() -> str:
    return "×" if _supports_unicode() else "x"


def _dash() -> str:
    return "—" if _supports_unicode() else "-"


def _tool_detail(doc: McpServer | None) -> str:
    """The '(Python, 3 tools)' qualifier for the checked line."""
    if doc is None:
        return ""
    n = len(doc.tools)
    word = "tool" if n == 1 else "tools"
    lang = doc.meta.language if doc.meta else None
    if not lang and getattr(doc, "source_mode", None) == SOURCE_RUNTIME:
        lang = "runtime"  # tools captured live — not a parsed source language
    if lang:
        return f" ({lang}, {n} {word})"
    if n:
        return f" ({n} {word})"
    return ""


def _checked_line(v: Verdict, doc: McpServer | None, sr: ScoreResult | None) -> str:
    name = (doc.meta.name if doc is not None and doc.meta else None) or "server"
    if v.tier == TIER_UNKNOWN:
        return f'mcpxray checked "{name}" {_dash()} no MCP tool definitions found.'
    score_part = f" {_dash()} score {sr.score}/100 ({sr.grade})" if sr is not None else ""
    return f'mcpxray checked "{name}"{_tool_detail(doc)}{score_part}'


def render_verdict(
    v: Verdict,
    *,
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
    details: bool = False,
) -> str:
    """Render a :class:`Verdict` as the human-facing card text."""
    lines: list[str] = [
        f"{_header(v)}  {_dash()} {v.headline}",
        "",
        _checked_line(v, doc, score_result),
        "",
    ]

    if v.tier == TIER_UNKNOWN:
        lines += [
            "mcpxray couldn't find tool definitions statically (unsupported",
            "language, or tools built dynamically at runtime).",
            "",
            "To check it anyway:",
            "  1. Capture its tools/list response to a JSON file, then run:",
            "       mcpxray check --manifest tools-list.json",
            "  2. Or spawn it and let mcpxray capture tools/list live:",
            "       mcpxray check --runtime --command '<launch cmd>'",
        ]
    elif v.reasons:
        lines.append("Why:")
        width = max(len(r.phrase) for r in v.reasons)
        for r in v.reasons:
            lines.append(f"  {_bullet()} {r.phrase.ljust(width)}   {r.rule_id} {_times()}{r.count}")
    else:
        lines.append("No issues found.")

    lines += ["", f"Recommendation: {v.recommendation}"]

    if v.tier != TIER_OK and v.reasons and not details:
        lines += ["", "Pass --details for the full finding list."]

    if details and doc is not None and doc.diagnostics:
        lines += [
            "",
            f"--- full findings ({len(doc.diagnostics)}) ---",
            plain_fmt.render(doc.diagnostics, doc=doc, score_result=score_result),
        ]

    return "\n".join(lines).rstrip() + "\n"


def render(
    diags: list[Diagnostic],
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
) -> str:
    """Standard formatter signature — render the card from a server + score."""
    if doc is None:
        return plain_fmt.render(diags, doc=doc, score_result=score_result)
    v = verdict(doc, score_result)
    return render_verdict(v, doc=doc, score_result=score_result, details=False)

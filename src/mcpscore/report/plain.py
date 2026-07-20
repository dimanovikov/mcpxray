"""Human-readable plain-text report."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcpscore.ir import Diagnostic, McpServer
    from mcpscore.score import ScoreResult


def render(
    diags: list[Diagnostic],
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
) -> str:
    lines: list[str] = []
    if score_result is not None:
        cap = "  [capped by error finding]" if score_result.capped else ""
        lines.append(f"Score: {score_result.score}/100 (grade {score_result.grade}){cap}")
        lines.append(
            f"  {score_result.errors} error(s), "
            f"{score_result.warnings} warning(s), {score_result.infos} info"
        )
    if not diags:
        lines.append("No findings.")
        return "\n".join(lines)
    for d in diags:
        loc = d.file or ""
        if d.line:
            loc = f"{loc}:{d.line}" if loc else f"line {d.line}"
        loc = f" {loc}" if loc else ""
        tool = f" [{d.tool}]" if d.tool else ""
        lines.append(f"{d.rule_id:<7} {d.severity:<8}{loc}{tool}  {d.message}")
    return "\n".join(lines)

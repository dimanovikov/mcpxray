"""GitHub Actions annotations (::error / ::warning / ::notice)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcpxray.ir import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING

if TYPE_CHECKING:
    from mcpxray.ir import Diagnostic, McpServer
    from mcpxray.score import ScoreResult

_LEVEL = {
    SEVERITY_ERROR: "error",
    SEVERITY_WARNING: "warning",
    SEVERITY_INFO: "notice",
}


def render(
    diags: list[Diagnostic],
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
) -> str:
    lines: list[str] = []
    for d in diags:
        level = _LEVEL.get(d.severity, "warning")
        loc = ""
        if d.file:
            loc = f" file={d.file}"
            if d.line:
                loc += f",line={d.line}"
        message = d.message.replace("\n", " ")
        lines.append(f"::{level}{loc}::{d.rule_id}: {message}")
    return "\n".join(lines)

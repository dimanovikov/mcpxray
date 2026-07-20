"""JSON report (machine-readable)."""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcpscore.ir import Diagnostic, McpServer
    from mcpscore.score import ScoreResult


def render(
    diags: list[Diagnostic],
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
) -> str:
    summary: dict[str, object] = {}
    if score_result is not None:
        summary = {
            "score": score_result.score,
            "grade": score_result.grade,
            "errors": score_result.errors,
            "warnings": score_result.warnings,
            "infos": score_result.infos,
            "capped": score_result.capped,
        }
    payload = {
        "summary": summary,
        "findings": [
            {
                "rule_id": d.rule_id,
                "severity": d.severity,
                "message": d.message,
                "tool": d.tool,
                "file": d.file,
                "line": d.line,
                "col": d.col,
            }
            for d in diags
        ],
    }
    if doc is not None:
        payload["server"] = {
            "name": doc.meta.name,
            "language": doc.meta.language,
            "tools": len(doc.tools),
            "source_mode": doc.source_mode,
        }
    return _json.dumps(payload, indent=2)

"""SARIF 2.1.0 report for GitHub code scanning and other SARIF consumers."""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

from mcpxray import __version__
from mcpxray.ir import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING

if TYPE_CHECKING:
    from mcpxray.ir import Diagnostic, McpServer
    from mcpxray.score import ScoreResult

# SARIF level mapping: error→error, warning→warning, info→note.
_LEVEL = {
    SEVERITY_ERROR: "error",
    SEVERITY_WARNING: "warning",
    SEVERITY_INFO: "note",
}


def render(
    diags: list[Diagnostic],
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
) -> str:
    rule_index: dict[str, int] = {}
    rules: list[dict] = []
    results: list[dict] = []

    for d in diags:
        if d.rule_id not in rule_index:
            rule_index[d.rule_id] = len(rules)
            rules.append(
                {
                    "id": d.rule_id,
                    "defaultConfiguration": {"level": _LEVEL.get(d.severity, "warning")},
                }
            )
        location: dict = {}
        if d.file:
            location = {
                "physicalLocation": {
                    "artifactLocation": {"uri": d.file},
                    "region": {"startLine": d.line or 1},
                }
            }
        result: dict = {
            "ruleId": d.rule_id,
            "level": _LEVEL.get(d.severity, "warning"),
            "message": {"text": d.message},
            "ruleIndex": rule_index[d.rule_id],
        }
        if location:
            result["locations"] = [location]
        results.append(result)

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "mcpxray",
                        "version": __version__,
                        "informationUri": "https://github.com/cloudroad-io/mcpxray",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return _json.dumps(sarif, indent=2)

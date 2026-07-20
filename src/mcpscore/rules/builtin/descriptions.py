"""Rules over tool descriptions: tool poisoning (MCP101) and hygiene (MCP107)."""

from __future__ import annotations

import re
import unicodedata

from mcpscore.ir import (
    RISK_CRITICAL,
    RISK_LOW,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Diagnostic,
    McpServer,
)
from mcpscore.rules.base import Rule, register_rule

# Indirect-prompt-injection signatures commonly embedded in poisoned tool
# descriptions (the channel the model trusts most — see Invariant Labs / OWASP).
_POISON_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(?:all\s+)?previous\s+(?:instructions?|prompts?|rules?)",
        r"disregard\s+(?:all|the|any|previous|above)",
        r"do\s+not\s+(?:show|reveal|display|mention|report)\s+(?:this|the|your)",
        r"instead\s+of\s+(?:responding|answering|following|showing|executing)",
        r"you\s+are\s+(?:now|actually)\s+(?:a|an)\b",
        r"(?:exfiltrate|upload|send|post|transmit|leak).{0,40}?"
        r"(?:to\s+(?:an?\s+)?(?:url|webhook|http|server|email|attacker)|https?://)",
        r"</?(?:system|secret|hidden|implicit)\s*>",
        r"before\s+answering(?:,|:)\s*(?:read|fetch|include|append)",
    )
]

_DESC_TOO_LONG = 4096  # bloats the context budget on every request


def _hidden_format_chars(text: str) -> list[str]:
    """Zero-width / bidi-override characters invisible to humans but read by the model."""
    return [ch for ch in text if unicodedata.category(ch) == "Cf"]


@register_rule
class ToolPoisoning(Rule):
    id = "MCP101"
    severity = SEVERITY_ERROR
    risk = RISK_CRITICAL

    def check(self, doc: McpServer):  # type: ignore[override]
        for tool in doc.tools:
            if not tool.description:
                continue
            for pattern in _POISON_PATTERNS:
                for m in pattern.finditer(tool.description):
                    yield Diagnostic(
                        self.id,
                        self.severity,
                        f"tool '{tool.name}': description contains a possible prompt-injection "
                        f"signature ({m.group(0)!r})",
                        tool=tool.name,
                        file=tool.source_path,
                        line=tool.line,
                    )
            hidden = _hidden_format_chars(tool.description)
            if hidden:
                yield Diagnostic(
                    self.id,
                    self.severity,
                    f"tool '{tool.name}': description contains hidden format/bidi characters "
                    f"({len(hidden)})",
                    tool=tool.name,
                    file=tool.source_path,
                    line=tool.line,
                )


@register_rule
class DescriptionHygiene(Rule):
    id = "MCP107"
    severity = SEVERITY_WARNING
    risk = RISK_LOW

    def check(self, doc: McpServer):  # type: ignore[override]
        for tool in doc.tools:
            if not tool.description or not tool.description.strip():
                yield Diagnostic(
                    self.id,
                    self.severity,
                    f"tool '{tool.name}': missing description — model can't decide when to call it",
                    tool=tool.name,
                    file=tool.source_path,
                    line=tool.line,
                )
            elif len(tool.description) > _DESC_TOO_LONG:
                yield Diagnostic(
                    self.id,
                    self.severity,
                    f"tool '{tool.name}': description is {len(tool.description)} chars "
                    f"(>{_DESC_TOO_LONG}); bloats the context budget on every request",
                    tool=tool.name,
                    file=tool.source_path,
                    line=tool.line,
                )

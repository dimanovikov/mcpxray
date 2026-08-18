"""Source-scanning rules: secret exposure (MCP102) and dangerous capabilities (MCP103)."""

from __future__ import annotations

import re

from mcpxray.ir import RISK_CRITICAL, RISK_HIGH, SEVERITY_ERROR, Diagnostic, McpServer
from mcpxray.rules.base import Rule, register_rule

# (pattern, human label). Tuned for precision — high-confidence secret shapes.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
        "private key",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI-style API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "GitHub token"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "GitLab token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"\baiza[0-9A-Za-z_-]{35,}\b"), "Google API key"),
    (
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password|passwd)\s*[=:]\s*"
            r"['\"]([A-Za-z0-9_\-+/=]{12,})['\"]"
        ),
        "hardcoded credential",
    ),
]

# Dangerous primitives an MCP tool should rarely invoke directly.
_RCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bos\.system\s*\("), "os.system (arbitrary shell command)"),
    (re.compile(r"\bos\.popen\s*\("), "os.popen (arbitrary shell command)"),
    (re.compile(r"(?<![\w.])eval\s*\("), "eval (arbitrary code execution)"),
    (re.compile(r"(?<![\w.])exec\s*\("), "exec (arbitrary code execution)"),
    (re.compile(r"\bpickle\.loads?\s*\("), "pickle deserialization (RCE risk)"),
    (re.compile(r"\bmarshal\.loads?\s*\("), "marshal deserialization (RCE risk)"),
    (
        re.compile(
            r"subprocess\.(?:run|Popen|call|check_output|check_call)"
            r"\s*\([^)]*?shell\s*=\s*True",
            re.S,
        ),
        "subprocess with shell=True (shell injection risk)",
    ),
]


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


@register_rule
class SecretExposure(Rule):
    id = "MCP102"
    severity = SEVERITY_ERROR
    risk = RISK_CRITICAL

    def applies(self, doc: McpServer) -> bool:
        return bool(doc.sources)

    def check(self, doc: McpServer):  # type: ignore[override]
        for path, text in doc.sources.items():
            for pattern, label in _SECRET_PATTERNS:
                for m in pattern.finditer(text):
                    yield Diagnostic(
                        self.id,
                        self.severity,
                        f"possible {label} exposed in source",
                        file=path,
                        line=_line_of(text, m.start()),
                    )


@register_rule
class DangerousCapabilities(Rule):
    id = "MCP103"
    severity = SEVERITY_ERROR
    risk = RISK_HIGH

    def applies(self, doc: McpServer) -> bool:
        return bool(doc.sources)

    def check(self, doc: McpServer):  # type: ignore[override]
        for path, text in doc.sources.items():
            for pattern, label in _RCE_PATTERNS:
                for m in pattern.finditer(text):
                    yield Diagnostic(
                        self.id,
                        self.severity,
                        f"dangerous capability: {label}",
                        file=path,
                        line=_line_of(text, m.start()),
                    )

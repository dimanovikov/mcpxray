"""Rule API, registry, and runner.

A :class:`Rule` inspects a :class:`~mcpscore.ir.McpServer` and yields
:class:`~mcpscore.ir.Diagnostic` findings. Builtins self-register via
:func:`register_rule`; external packages declare an entry-point in the
``mcpscore.rules`` group. ``run_all`` applies every applicable rule, sorts the
findings by severity (errors first), and mirrors them onto ``doc.diagnostics``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from mcpscore.ir import (
    RISK_MEDIUM,
    SEVERITY_WARNING,
    Diagnostic,
    McpServer,
    severity_rank,
)

_RULES: list[type[Rule]] = []


class Rule(ABC):
    """Base class for all lint rules."""

    id: str = ""
    severity: str = SEVERITY_WARNING
    risk: str = RISK_MEDIUM  # scoring weight

    def applies(self, doc: McpServer) -> bool:  # noqa: ARG002
        """Override to gate the rule (e.g. source-only vs manifest-only)."""
        return True

    @abstractmethod
    def check(self, doc: McpServer) -> Iterable[Diagnostic]:
        """Yield findings for this rule."""


def register_rule(cls: type[Rule]) -> type[Rule]:
    """Class decorator: register a :class:`Rule` subclass."""
    _RULES.append(cls)
    return cls


def rules() -> list[type[Rule]]:
    """All registered rule classes (builtins first, registration order)."""
    return list(_RULES)


def run_all(doc: McpServer) -> list[Diagnostic]:
    """Run every applicable rule; return findings sorted by severity (errors first)."""
    diags: list[Diagnostic] = []
    for cls in _RULES:
        rule = cls()
        if rule.applies(doc):
            diags.extend(rule.check(doc))
    diags.sort(key=lambda d: -severity_rank(d.severity))
    doc.diagnostics.extend(diags)
    return diags

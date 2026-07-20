"""Lint rules for MCP servers."""

from __future__ import annotations

from mcpscore.rules import builtin  # noqa: F401  — registers builtin rules
from mcpscore.rules.base import Rule, register_rule, rules, run_all

__all__ = ["Rule", "register_rule", "rules", "run_all"]

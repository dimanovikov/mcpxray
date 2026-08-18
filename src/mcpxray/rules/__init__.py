"""Lint rules for MCP servers."""

from __future__ import annotations

from mcpxray.rules import builtin  # noqa: F401  — registers builtin rules
from mcpxray.rules.base import Rule, register_rule, rules, run_all

__all__ = ["Rule", "register_rule", "rules", "run_all"]

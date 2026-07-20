"""Supply-chain rule: unpinned dependencies without a lockfile (MCP108)."""

from __future__ import annotations

from mcpscore.ir import RISK_MEDIUM, SEVERITY_WARNING, Diagnostic, McpServer
from mcpscore.rules.base import Rule, register_rule


def _is_pinned(spec: str) -> bool:
    # Exact pin (==1.2.3) or compatible release (~=1.2) is reproducible; anything
    # else (>=, <, *, latest) drifts between installs.
    return "==" in spec or spec.startswith("~=")


@register_rule
class UnpinnedDependencies(Rule):
    id = "MCP108"
    severity = SEVERITY_WARNING
    risk = RISK_MEDIUM

    def applies(self, doc: McpServer) -> bool:
        # A lockfile makes installs reproducible regardless of pin style.
        return bool(doc.dependencies) and not doc.lockfiles

    def check(self, doc: McpServer):  # type: ignore[override]
        unpinned = sorted(n for n, spec in doc.dependencies.items() if not _is_pinned(spec))
        if not unpinned:
            return
        shown = ", ".join(unpinned[:5])
        more = f" (+{len(unpinned) - 5} more)" if len(unpinned) > 5 else ""
        yield Diagnostic(
            self.id,
            self.severity,
            f"{len(unpinned)} unpinned dependencies and no lockfile: {shown}{more}",
            file=doc.meta.path,
        )

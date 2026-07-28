"""Supply-chain rule: unpinned dependencies without a lockfile (MCP108)."""

from __future__ import annotations

import re

from mcpscore.ir import RISK_MEDIUM, SEVERITY_WARNING, Diagnostic, McpServer
from mcpscore.rules.base import Rule, register_rule

# npm: an exact bare version is reproducible; carets/tilde/ranges/wildcards/tags
# drift. Pre-release/build suffixes (``1.2.3-beta.1``) still pin exactly. A bare
# package name (``flask``) or a pip range (``>=2``) deliberately fails to match.
_NPM_PIN_RE = re.compile(r"^[v=]?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _is_pinned(spec: str) -> bool:
    """True if ``spec`` makes an install reproducible.

    Covers both ecosystems an MCP server can declare:
    * **pip** — exact ``==1.2.3`` or compatible-release ``~=1.2``.
    * **npm** — an exact bare version ``1.2.3`` / ``v1.2.3`` / ``=1.2.3``.
    Ranges and floating tags (``>=``, ``^``, ``~``, ``*``, ``latest``, ``1.x``)
    are *not* pinned — they resolve differently between installs.
    """
    spec = spec.strip()
    if not spec:
        return False
    if "==" in spec or spec.startswith("~="):  # pip
        return True
    return bool(_NPM_PIN_RE.match(spec))  # npm exact version


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

"""Supply-chain rule: unpinned dependencies without a lockfile (MCP108)."""

from __future__ import annotations

import re

from mcpxray.fix import exact_pin
from mcpxray.ir import RISK_MEDIUM, SEVERITY_WARNING, Diagnostic, Fix, McpServer, TextEdit
from mcpxray.rules.base import Rule, register_rule

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


def _pin_edits(
    dependencies: dict[str, str], unpinned: list[str], dep_file: str, *, pip: bool
) -> list[TextEdit]:
    """Literal ``TextEdit``\\s pinning each unpinned dep to its concrete floor.

    Skips specs with no resolvable floor (``*``/``latest``/bare) or with extras
    / env markers (``name[extra]`` / ``name ; python>'3'``) — rewriting those
    textually is unsafe, so they're left for manual pinning. Each edit anchors on
    the dep name so the fix engine's uniqueness check lands on the right site.
    """
    edits: list[TextEdit] = []
    for name in unpinned:
        spec = dependencies[name]
        if "[" in spec or ";" in spec:
            continue
        pinned = exact_pin(spec, pip=pip)
        if pinned is None:
            continue
        if pip:  # pyproject array element: ``"name<spec>"``
            edits.append(TextEdit(old=f"{name}{spec}", new=f"{name}{pinned}"))
        else:  # package.json pair: ``"name": "<spec>"``
            edits.append(TextEdit(old=f'"{name}": "{spec}"', new=f'"{name}": "{pinned}"'))
    return edits


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
        diag = Diagnostic(
            self.id,
            self.severity,
            f"{len(unpinned)} unpinned dependencies and no lockfile: {shown}{more}",
            file=doc.meta.path,
        )
        dep_file = doc.dep_file
        if dep_file:
            edits = _pin_edits(
                doc.dependencies, unpinned, dep_file, pip=not dep_file.endswith("package.json")
            )
            if edits:
                diag.fix = Fix(
                    description="pin unpinned dependencies to their declared floor version",
                    file=dep_file,
                    edits=edits,
                )
        yield diag

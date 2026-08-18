"""Auto-fix machinery: turn rule-proposed :class:`~mcpxray.ir.Fix`es into file
edits and diffs.

Only **MCP108** (unpinned dependencies) is mechanically fixable today — it pins
a floating version spec to its concrete floor (``requests>=2.30`` →
``requests==2.30.0``, ``"^1.2.3"`` → ``"1.2.3"``). Specs with no resolvable
floor (``*``, ``latest``, a bare name like ``flask``) are skipped and left for
manual pinning — mcpxray never invents a version by resolving a registry.

``--fix`` is opt-in and **static-source-only** (it rewrites files in place);
``--diff`` prints a unified diff of the same edits without writing. Both flow
through :func:`plan_fixes`, which collects every diagnostic's ``fix`` and groups
it by file.

Safety: every edit is a *literal* substring replacement applied only when its
``old`` text occurs exactly once in the file (see :func:`_apply_edits`) — so a
spec that doesn't match the common form, or that would match more than one site,
is skipped rather than applied wrongly. Writes are atomic (temp file + replace).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcpxray.ir import Fix, McpServer, TextEdit

# A concrete MAJOR.MINOR.PATCH (optionally with pre-release/build) extractable
# from a floating spec — the floor it pins down to. The lookbehind only rejects a
# preceding digit/dot (so we don't match a partial version mid-number); version
# prefix chars (``v``/``=``/``^``/``~``/``>``/``<``) and letters are allowed.
_FLOOR_RE = re.compile(r"(?<![0-9.])(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)")


def pin_floor(spec: str) -> str | None:
    """The concrete ``X.Y.Z`` a floating spec resolves down to, or ``None``.

    ``^1.2.3`` / ``~1.2.3`` / ``>=1.2.3`` / ``=1.2.3`` / ``v1.2.3`` → ``1.2.3``.
    ``*`` / ``latest`` / a bare name (``flask``) / ``1.x`` / ``>=2`` → ``None``
    (no full floor → can't pin without resolving from a registry).
    """
    m = _FLOOR_RE.search(spec)
    return m.group(1) if m else None


def exact_pin(spec: str, *, pip: bool) -> str | None:
    """Exact pinned form of ``spec`` for its ecosystem, or ``None`` if unresolvable.

    pip → ``==X.Y.Z``; npm → ``X.Y.Z``. Returns ``None`` when :func:`pin_floor`
    can't find a floor.
    """
    floor = pin_floor(spec)
    if floor is None:
        return None
    return f"=={floor}" if pip else floor


@dataclass
class ApplySummary:
    """Outcome of :func:`apply_fixes`: how much changed and what was declined."""

    files_changed: int = 0
    edits_applied: int = 0
    skipped: list[str] = field(default_factory=list)


def plan_fixes(doc: McpServer) -> list[Fix]:
    """Collect every diagnostic's ``fix`` and merge them into one :class:`Fix` per file."""
    by_file: dict[str, Fix] = {}
    for diag in doc.diagnostics:
        fix = diag.fix
        if fix is None:
            continue
        bucket = by_file.setdefault(fix.file, Fix(description=fix.description, file=fix.file))
        bucket.edits.extend(fix.edits)
    return list(by_file.values())


def _apply_edits(text: str, edits: list[TextEdit]) -> tuple[str, list[TextEdit], list[str]]:
    """Apply ``edits`` to ``text``; return ``(new_text, applied, skipped_messages)``.

    An edit is applied only when its ``old`` occurs exactly once and its span
    doesn't overlap another kept edit. Absent/ambiguous/overlapping edits are
    skipped (never applied partially).
    """
    spans: list[tuple[int, int, TextEdit]] = []
    skipped: list[str] = []
    for edit in edits:
        if not edit.old or edit.old == edit.new:
            continue
        first = text.find(edit.old)
        if first == -1:
            skipped.append(f"not found in source: {edit.old!r}")
            continue
        if text.find(edit.old, first + 1) != -1:
            skipped.append(f"ambiguous — matches more than one site: {edit.old!r}")
            continue
        spans.append((first, first + len(edit.old), edit))

    spans.sort()
    kept: list[TextEdit] = []
    last_end = -1
    for start, end, edit in spans:
        if start < last_end:
            skipped.append(f"overlaps another edit: {edit.old!r}")
            continue
        kept.append(edit)
        last_end = end

    out = text
    for edit in kept:  # each `old` is unique, so order is irrelevant
        out = out.replace(edit.old, edit.new, 1)
    return out, kept, skipped


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".mcpxray-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def apply_fixes(fixes: list[Fix]) -> ApplySummary:
    """Write every fix's file in place (atomic); return an :class:`ApplySummary`."""
    summary = ApplySummary()
    for fix in fixes:
        path = Path(fix.file)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            summary.skipped.append(f"unreadable file: {fix.file}")
            continue
        new_text, applied, skipped = _apply_edits(text, fix.edits)
        summary.skipped.extend(skipped)
        if not applied:
            continue
        _atomic_write(path, new_text)
        summary.files_changed += 1
        summary.edits_applied += len(applied)
    return summary


def render_diff(fixes: list[Fix]) -> str:
    """Unified diff of every fix's planned edits — writes nothing."""
    parts: list[str] = []
    for fix in fixes:
        path = Path(fix.file)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        new_text, _applied, _skipped = _apply_edits(text, fix.edits)
        diff = difflib.unified_diff(
            text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=path.name,
            tofile=path.name,
        )
        parts.append("".join(diff))
    return "".join(parts)


def has_pending(fixes: list[Fix]) -> bool:
    """True if any planned fix carries at least one edit."""
    return any(fix.edits for fix in fixes)

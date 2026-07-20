"""Score engine — collapse findings into a 0-100 score with an error cap.

Mirrors OpenSSF Scorecard's shape (risk-weighted, hard cap so a single critical
finding can't be diluted): each finding deducts points by severity, and any
ERROR-severity finding caps the result at :data:`~mcpscore.ir.ERROR_SCORE_CAP`
so a server with a leaked secret or poisoned tool never scores green.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcpscore.ir import ERROR_SCORE_CAP, SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING, McpServer

# Points deducted per finding, by severity.
_DEDUCTION = {
    SEVERITY_ERROR: 20,
    SEVERITY_WARNING: 6,
    SEVERITY_INFO: 1,
}

_MAX_SCORE = 100


@dataclass(frozen=True)
class ScoreResult:
    """The outcome of scoring a server."""

    score: int
    errors: int
    warnings: int
    infos: int
    capped: bool  # True when the error-cap lowered the score

    @property
    def grade(self) -> str:
        """Letter grade: A ≥90, B ≥80, C ≥70, D ≥60, F <60."""
        if self.score >= 90:
            return "A"
        if self.score >= 80:
            return "B"
        if self.score >= 70:
            return "C"
        if self.score >= 60:
            return "D"
        return "F"

    def passed(self, fail_under: int) -> bool:
        return self.score >= fail_under


def score(doc: McpServer) -> ScoreResult:
    """Score a server from its diagnostics (run :func:`mcpscore.rules.run_all` first)."""
    errors = sum(1 for d in doc.diagnostics if d.severity == SEVERITY_ERROR)
    warnings = sum(1 for d in doc.diagnostics if d.severity == SEVERITY_WARNING)
    infos = sum(1 for d in doc.diagnostics if d.severity == SEVERITY_INFO)

    deducted = sum(_DEDUCTION.get(d.severity, 0) for d in doc.diagnostics)
    raw = _MAX_SCORE - deducted

    capped = errors > 0
    final = min(raw, ERROR_SCORE_CAP) if capped else raw
    final = max(0, min(_MAX_SCORE, final))

    return ScoreResult(
        score=final,
        errors=errors,
        warnings=warnings,
        infos=infos,
        capped=capped,
    )

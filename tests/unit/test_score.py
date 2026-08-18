"""Unit tests for the score engine."""

from __future__ import annotations

from pathlib import Path

from mcpxray.extract import extractor_for
from mcpxray.ir import (
    ERROR_SCORE_CAP,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Diagnostic,
    McpServer,
    ServerMeta,
)
from mcpxray.rules import run_all
from mcpxray.score import score

FIXTURES = Path(__file__).parent.parent / "fixtures" / "servers"


def _server(*diags: Diagnostic) -> McpServer:
    s = McpServer(meta=ServerMeta(name="x"))
    s.diagnostics.extend(diags)
    return s


class TestScoreModel:
    def test_clean_is_100_grade_a(self):
        r = score(_server())
        assert r.score == 100
        assert r.grade == "A"
        assert not r.capped

    def test_warning_only_not_capped(self):
        r = score(_server(Diagnostic("MCP107", SEVERITY_WARNING, "w")))
        assert r.score == 94
        assert r.grade == "A"
        assert not r.capped

    def test_error_caps_at_60(self):
        r = score(_server(Diagnostic("MCP102", SEVERITY_ERROR, "e")))
        assert r.capped is True
        assert r.score == ERROR_SCORE_CAP
        assert r.grade == "D"

    def test_many_warnings_trend_to_zero(self):
        diags = [Diagnostic("MCP104", SEVERITY_WARNING, "w") for _ in range(30)]
        r = score(_server(*diags))
        assert r.score == 0
        assert r.grade == "F"
        assert not r.capped

    def test_info_minimal_deduction(self):
        r = score(_server(Diagnostic("X", SEVERITY_INFO, "i")))
        assert r.score == 99

    def test_fail_under(self):
        r = score(_server(Diagnostic("MCP102", SEVERITY_ERROR, "e")))
        assert r.passed(50) is True
        assert r.passed(70) is False

    def test_many_errors_drop_below_cap(self):
        # 3 errors: 100 - 60 = 40, which is below the 60 cap
        r = score(_server(*[Diagnostic("MCP102", SEVERITY_ERROR, "e") for _ in range(3)]))
        assert r.score == 40
        assert r.capped


class TestScoreOnFixtures:
    def _score(self, rel: str) -> object:
        path = FIXTURES / rel
        doc = extractor_for(path).extract(path)
        run_all(doc)
        return score(doc)

    def test_clean_fixture_scores_100(self):
        assert self._score("clean").score == 100

    def test_leaky_fixture_capped(self):
        r = self._score("leaky")
        assert r.capped is True
        assert r.score <= ERROR_SCORE_CAP
        assert r.errors >= 2  # secret + rce

    def test_poisoned_fixture_capped(self):
        assert self._score("poisoned").capped is True

"""Unit tests for report formatters and the badge."""

from __future__ import annotations

import json as _json

from mcpscore.badge import badge_svg
from mcpscore.ir import SEVERITY_ERROR, SEVERITY_WARNING, Diagnostic
from mcpscore.report import SUPPORTED_FORMATS, plain, render, sarif
from mcpscore.report import github as github_fmt
from mcpscore.report import json as json_fmt
from mcpscore.score import ScoreResult

DIAGS = [
    Diagnostic("MCP102", SEVERITY_ERROR, "leaked key", file="srv.py", line=4),
    Diagnostic("MCP107", SEVERITY_WARNING, "no description", tool="raw"),
]
SCORE = ScoreResult(score=60, errors=1, warnings=1, infos=0, capped=True)


class TestPlain:
    def test_includes_score_and_findings(self):
        out = plain.render(DIAGS, None, SCORE)
        assert "Score: 60/100 (grade D)" in out
        assert "1 error(s), 1 warning(s)" in out
        assert "MCP102  error    srv.py:4" in out
        assert "leaked key" in out

    def test_no_findings(self):
        assert "No findings." in plain.render([], None, None)


class TestJson:
    def test_valid_json_with_summary(self):
        out = json_fmt.render(DIAGS, None, SCORE)
        payload = _json.loads(out)
        assert payload["summary"]["score"] == 60
        assert payload["summary"]["grade"] == "D"
        assert payload["findings"][0]["rule_id"] == "MCP102"
        assert payload["findings"][0]["file"] == "srv.py"

    def test_no_score_omits_summary_fields(self):
        payload = _json.loads(json_fmt.render(DIAGS, None, None))
        assert payload["summary"] == {}
        assert len(payload["findings"]) == 2


class TestGithub:
    def test_annotation_format(self):
        out = github_fmt.render(DIAGS, None, None)
        assert "::error file=srv.py,line=4::MCP102: leaked key" in out
        assert "::warning" in out  # the MCP107 finding


class TestSarif:
    def test_valid_sarif_skeleton(self):
        out = sarif.render(DIAGS, None, None)
        doc = _json.loads(out)
        assert doc["$schema"].endswith("sarif-2.1.0.json")
        assert doc["version"] == "2.1.0"
        run = doc["runs"][0]
        assert run["tool"]["driver"]["name"] == "mcpscore"
        assert len(run["results"]) == 2

    def test_level_mapping_and_location(self):
        doc = _json.loads(sarif.render(DIAGS, None, None))
        r0 = doc["runs"][0]["results"][0]
        assert r0["level"] == "error"
        assert r0["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "srv.py"
        assert r0["locations"][0]["physicalLocation"]["region"]["startLine"] == 4

    def test_rules_deduplicated(self):
        diags = [
            Diagnostic("MCP102", SEVERITY_ERROR, "a", file="x", line=1),
            Diagnostic("MCP102", SEVERITY_ERROR, "b", file="x", line=2),
        ]
        doc = _json.loads(sarif.render(diags, None, None))
        assert len(doc["runs"][0]["tool"]["driver"]["rules"]) == 1


class TestDispatcher:
    def test_supported_formats(self):
        assert set(SUPPORTED_FORMATS) == {"plain", "json", "github", "sarif"}

    def test_each_format_renders(self):
        for fmt in SUPPORTED_FORMATS:
            assert isinstance(render(DIAGS, fmt, score_result=SCORE), str)

    def test_unknown_format_raises(self):
        try:
            render(DIAGS, "xml")
        except ValueError as e:
            assert "xml" in str(e)
        else:
            raise AssertionError("expected ValueError for unknown format")


class TestBadge:
    def test_svg_structure(self):
        svg = badge_svg(SCORE)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert "60/100" in svg
        assert "#fe7d37" in svg  # score 60 → grade D → orange

    def test_grade_color_varies(self):
        green = badge_svg(ScoreResult(100, 0, 0, 0, capped=False))
        assert "#4c1" in green  # A = brightgreen

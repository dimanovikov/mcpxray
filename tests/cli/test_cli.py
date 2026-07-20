"""End-to-end CLI tests — drive the Typer app through a CliRunner.

These exercise the full pipeline (extract → run_all → score → render) the way a
user would, asserting on exit codes and observable output rather than internals.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcpscore import __version__
from mcpscore.cli import app

FIXTURES = Path(__file__).parent.parent / "fixtures" / "servers"

runner = CliRunner()


def _invoke(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture
def clean() -> Path:
    return FIXTURES / "clean"


@pytest.fixture
def leaky() -> Path:
    return FIXTURES / "leaky"


class TestVersion:
    def test_prints_version(self):
        r = _invoke("version")
        assert r.exit_code == 0
        assert __version__ in r.stdout


class TestScan:
    def test_clean_exits_zero(self, clean):
        r = _invoke("scan", str(clean))
        assert r.exit_code == 0
        assert "100/100" in r.stdout
        assert "No findings." in r.stdout

    def test_leaky_advisory_exits_zero_without_check(self, leaky):
        # Findings are printed, but scan is advisory unless --check gates it.
        r = _invoke("scan", str(leaky))
        assert r.exit_code == 0
        assert "MCP102" in r.stdout
        assert "MCP103" in r.stdout

    def test_leaky_check_exits_one(self, leaky):
        r = _invoke("scan", str(leaky), "--check")
        assert r.exit_code == 1

    def test_sarif_is_valid(self, leaky):
        r = _invoke("scan", str(leaky), "-f", "sarif")
        assert r.exit_code == 0
        doc = _json.loads(r.stdout)
        assert doc["version"] == "2.1.0"
        assert len(doc["runs"][0]["results"]) >= 2

    def test_github_annotations(self, leaky):
        r = _invoke("scan", str(leaky), "-f", "github")
        assert r.exit_code == 0
        assert "::error file=" in r.stdout

    def test_json_carries_score(self, leaky):
        r = _invoke("scan", str(leaky), "-f", "json")
        assert r.exit_code == 0
        payload = _json.loads(r.stdout)
        assert payload["summary"]["score"] <= 60
        assert payload["summary"]["capped"] is True

    def test_manifest_path(self):
        r = _invoke(
            "scan",
            "--manifest",
            str(FIXTURES / "clean_manifest.json"),
        )
        assert r.exit_code == 0
        assert "100/100" in r.stdout

    def test_no_extractor_exits_two(self, tmp_path):
        target = tmp_path / "not-a-server.txt"
        target.write_text("hello", encoding="utf-8")
        r = _invoke("scan", str(target))
        assert r.exit_code == 2
        assert "no extractor matched" in (r.stderr or r.stdout)

    def test_unknown_format_errors(self, leaky):
        r = _invoke("scan", str(leaky), "-f", "xml")
        assert r.exit_code == 1
        assert isinstance(r.exception, ValueError)


class TestScore:
    def test_clean_is_hundred(self, clean):
        r = _invoke("score", str(clean))
        assert r.exit_code == 0
        assert "100/100" in r.stdout
        assert "grade A" in r.stdout

    def test_leaky_capped_below_sixty(self, leaky):
        r = _invoke("score", str(leaky))
        assert r.exit_code == 0  # advisory without --fail-under
        assert "capped by error finding" in r.stdout
        # grab the number out of "score N/100"
        num = int(r.stdout.split("score")[1].split("/")[0].strip())
        assert num <= 60

    def test_fail_under_gates(self, leaky):
        r = _invoke("score", str(leaky), "--fail-under", "80")
        assert r.exit_code == 1

    def test_fail_under_passes_when_met(self, leaky):
        r = _invoke("score", str(leaky), "--fail-under", "0")
        assert r.exit_code == 0


class TestBadge:
    def test_score_to_file(self, tmp_path):
        out = tmp_path / "badge.svg"
        r = _invoke("badge", "--score", "92", "-o", str(out))
        assert r.exit_code == 0
        svg = out.read_text(encoding="utf-8")
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        assert "92/100" in svg

    def test_from_path_to_stdout(self, clean):
        r = _invoke("badge", str(clean), "-o", "-")
        assert r.exit_code == 0
        assert r.stdout.lstrip().startswith("<svg")

    def test_needs_score_or_path(self):
        r = _invoke("badge")
        assert r.exit_code == 2

"""P0-2: a tree the scanner could not read must not be awarded a grade.

Before this, pointing `mcpxray` at a Python MCP server it did not understand
produced `100/100 (grade A)` and "No findings" — a clean bill of health for a
file that was never analysed. That is the worst possible failure mode for a
security tool, because it is indistinguishable from a genuine pass.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mcpxray.cli import app

runner = CliRunner()


def _server(tmp_path: Path, body: str) -> Path:
    (tmp_path / "server.py").write_text(body, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n', encoding="utf-8"
    )
    return tmp_path


OPAQUE = "# a Python file the extractor finds no MCP surface in\nVALUE = 1\n"


class TestUnanalysedIsNotAPass:
    def test_scan_json_withholds_the_grade(self, tmp_path: Path):
        r = runner.invoke(app, ["scan", str(_server(tmp_path, OPAQUE)), "--format", "json"])
        import json

        payload = json.loads(r.stdout)
        assert payload["summary"]["analysed"] is False
        assert payload["summary"]["grade"] is None

    def test_scan_text_says_so_plainly(self, tmp_path: Path):
        r = runner.invoke(app, ["scan", str(_server(tmp_path, OPAQUE))])
        assert "grade A" not in r.stdout
        assert "not analysed" in r.stdout.lower()

    def test_score_exits_non_zero(self, tmp_path: Path):
        r = runner.invoke(app, ["score", str(_server(tmp_path, OPAQUE))])
        assert r.exit_code != 0, "an unanalysed server must not pass a CI gate"

    def test_a_real_server_still_scores(self, tmp_path: Path):
        body = (
            "from mcp.server.fastmcp import FastMCP\n"
            "mcp = FastMCP('demo')\n\n"
            "@mcp.tool()\n"
            "def add(a: int, b: int) -> int:\n"
            '    """Add two numbers."""\n'
            "    return a + b\n"
        )
        r = runner.invoke(app, ["score", str(_server(tmp_path, body))])
        assert r.exit_code == 0
        assert "grade" in r.stdout.lower()


class TestVersionFlag:
    """P2-7: only a `version` subcommand existed. Every other CLI answers
    `--version`, and the first thing anyone types when filing a bug is that."""

    def test_version_flag_prints_the_version(self):
        from mcpxray import __version__

        r = runner.invoke(app, ["--version"])
        assert r.exit_code == 0
        assert __version__ in r.stdout


class TestRuntimeWarnsBeforeSpawning:
    """P1-5: --runtime launches the server being vetted, on this machine, with
    the user's own privileges. That is a reasonable thing to offer and an
    unreasonable thing to do silently in a tool whose job is judging whether
    that server is safe."""

    def test_warning_names_the_risk(self, tmp_path: Path, monkeypatch):
        from mcpxray import cli as cli_mod

        def _refuse(*a, **kw):
            raise cli_mod.CaptureError("spawn declined in test")

        monkeypatch.setattr(cli_mod, "capture_tools", _refuse)
        r = runner.invoke(app, ["scan", str(tmp_path), "--runtime", "--command", "python -m srv"])
        combined = r.stdout + (r.stderr or "")
        assert "runs" in combined.lower() or "execut" in combined.lower(), combined

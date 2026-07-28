"""End-to-end CLI tests for the `check` command (friendly verdict card)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

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


@pytest.fixture
def poisoned() -> Path:
    return FIXTURES / "poisoned"


@pytest.fixture
def unpinned() -> Path:
    return FIXTURES / "unpinned"


@pytest.fixture
def typescript_clean() -> Path:
    return FIXTURES / "typescript_clean"


@pytest.fixture
def typescript_leaky() -> Path:
    return FIXTURES / "typescript_leaky"


class TestCheckTiers:
    def test_clean_is_ok_exit_zero(self, clean):
        r = _invoke("check", str(clean))
        assert r.exit_code == 0
        assert "OK" in r.stdout
        assert "Looks clean" in r.stdout

    def test_leaky_is_danger_exit_one(self, leaky):
        r = _invoke("check", str(leaky))
        assert r.exit_code == 1
        assert "DANGER" in r.stdout

    def test_poisoned_is_danger_with_reason(self, poisoned):
        r = _invoke("check", str(poisoned))
        assert r.exit_code == 1
        assert "DANGER" in r.stdout
        assert "poisoning" in r.stdout.lower()

    def test_unpinned_is_caution_exit_zero(self, unpinned):
        r = _invoke("check", str(unpinned))
        assert r.exit_code == 0
        assert "CAUTION" in r.stdout


class TestCheckOptions:
    def test_details_flag(self, leaky):
        r = _invoke("check", str(leaky), "--details")
        assert r.exit_code == 1
        assert "full findings" in r.stdout

    def test_short_v_flag(self, leaky):
        r = _invoke("check", str(leaky), "-v")
        assert r.exit_code == 1
        assert "full findings" in r.stdout

    def test_manifest(self):
        r = _invoke("check", "--manifest", str(FIXTURES / "clean_manifest.json"))
        assert r.exit_code == 0
        assert "OK" in r.stdout

    def test_dot_uses_cwd(self, clean, monkeypatch):
        monkeypatch.chdir(clean)
        r = _invoke("check", ".")
        assert r.exit_code == 0
        assert "OK" in r.stdout


class TestCheckEdgeCases:
    def test_non_python_is_unknown_exit_zero(self, tmp_path):
        target = tmp_path / "not-a-server.txt"
        target.write_text("hello", encoding="utf-8")
        r = _invoke("check", str(target))
        assert r.exit_code == 0
        assert "UNKNOWN" in r.stdout
        assert "--manifest" in r.stdout

    def test_missing_path_exit_two(self):
        r = _invoke("check", "no_such_path_xyz")
        assert r.exit_code == 2
        assert "path not found" in (r.stderr or r.stdout)

    def test_fail_under_gate_independent_of_tier(self, unpinned):
        # unpinned is caution (exit 0) without a gate ...
        assert _invoke("check", str(unpinned)).exit_code == 0
        # ... but --fail-under promotes it to a CI failure without changing the tier.
        gated = _invoke("check", str(unpinned), "--fail-under", "100")
        assert gated.exit_code == 1
        assert "CAUTION" in gated.stdout


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
class TestCheckUrl:
    @staticmethod
    def _remote_from(clean: Path, parent: Path) -> Path:
        remote = parent / "remote"
        remote.mkdir()
        # Byte copy: the fixture may be cp1252 (em-dash), so don't force utf-8.
        (remote / "server.py").write_bytes(clean.joinpath("server.py").read_bytes())
        subprocess.run(["git", "init", "-q"], cwd=remote, check=True)
        subprocess.run(["git", "add", "."], cwd=remote, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
            cwd=remote,
            check=True,
        )
        return remote

    def test_url_clones_and_scores(self, clean, tmp_path):
        remote = self._remote_from(clean, tmp_path)
        url = f"file:///{remote.as_posix()}"
        r = _invoke("check", url)
        assert r.exit_code == 0
        assert "OK" in r.stdout


@needs_git
class TestCheckScope:
    """A cloned repo must be scoped to the server source, not its test tree.

    Reproduces the python-sdk demo failure mode: fake secrets in ``tests/``
    inflating a clean server to a spurious 🔴. Auto-scoping to the entry point
    must exclude them; ``--scope tests`` confirms they really are there.
    """

    @staticmethod
    def _src_layout_remote(parent: Path) -> Path:
        remote = parent / "remote"
        remote.mkdir(parents=True)
        (remote / "pyproject.toml").write_text(
            '[project.scripts]\nmyserver = "myserver.main:app"\n', encoding="utf-8"
        )
        (remote / "src" / "myserver").mkdir(parents=True)
        (remote / "src" / "myserver" / "main.py").write_text(
            "from mcp import FastMCP\nmcp = FastMCP('s')\n\n"
            "@mcp.tool()\n"
            "def add(a: int, b: int) -> int:\n"
            '    """Add two ints."""\n'
            "    return a + b\n",
            encoding="utf-8",
        )
        (remote / "tests").mkdir()
        (remote / "tests" / "test_keys.py").write_text(
            'LEAKED = "sk-1234567890abcdef1234567890abcdef"\n', encoding="utf-8"
        )
        for args in (
            ["git", "init", "-q"],
            ["git", "add", "."],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        ):
            subprocess.run(args, cwd=remote, check=True)
        return remote

    def test_auto_scope_check_is_ok(self, tmp_path):
        remote = self._src_layout_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        r = _invoke("check", url)
        assert r.exit_code == 0
        assert "OK" in r.stdout
        assert "DANGER" not in r.stdout

    def test_scan_auto_scope_excludes_test_secrets(self, tmp_path):
        # Auto-scoped to src/myserver: the fake key in tests/ is never scanned.
        remote = self._src_layout_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        payload = json.loads(_invoke("scan", url, "-f", "json").stdout)
        rules = {f["rule_id"] for f in payload["findings"]}
        assert "MCP102" not in rules

    def test_scan_force_scope_tests_finds_the_secret(self, tmp_path):
        # Same repo pointed straight at tests/ — proves the key is real and that
        # auto-scoping (not a broken detector) is what excluded it. ``scan`` is
        # used because the verdict engine treats a tool-less tree as UNKNOWN.
        remote = self._src_layout_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        payload = json.loads(_invoke("scan", url, "--scope", "tests", "-f", "json").stdout)
        rules = {f["rule_id"] for f in payload["findings"]}
        assert "MCP102" in rules

    def test_scope_override_points_at_server(self, tmp_path):
        remote = self._src_layout_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        r = _invoke("check", url, "--scope", "src/myserver")
        assert r.exit_code == 0
        assert "OK" in r.stdout


class TestCheckTypeScript:
    """A TypeScript server must be analysed statically (not ⚪ UNKNOWN)."""

    def test_clean_ts_is_ok_not_unknown(self, typescript_clean):
        r = _invoke("check", str(typescript_clean))
        assert r.exit_code == 0
        assert "OK" in r.stdout
        assert "UNKNOWN" not in r.stdout
        assert "typescript" in r.stdout  # the (typescript, N tools) qualifier

    def test_leaky_ts_is_danger(self, typescript_leaky):
        # Proves .sources text flows to MCP102 — a hardcoded key in a .ts file.
        r = _invoke("check", str(typescript_leaky))
        assert r.exit_code == 1
        assert "DANGER" in r.stdout

    def test_scan_reports_ts_server(self, typescript_clean):
        payload = json.loads(_invoke("scan", str(typescript_clean), "-f", "json").stdout)
        assert payload["server"]["language"] == "typescript"
        assert payload["server"]["tools"] == 3


@needs_git
class TestCheckTypeScriptScope:
    """A cloned TS repo is scoped to its server source, not the test tree."""

    @staticmethod
    def _ts_remote(parent: Path) -> Path:
        remote = parent / "remote"
        remote.mkdir(parents=True)
        (remote / "package.json").write_text(
            '{"name": "ts-demo", "version": "0.0.0"}\n', encoding="utf-8"
        )
        (remote / "src").mkdir(parents=True)
        (remote / "src" / "server.ts").write_text(
            "const s = { tool: () => {} };\n"
            's.tool("ping", "health check", {}, async () => ({}));\n',
            encoding="utf-8",
        )
        (remote / "tests").mkdir()
        (remote / "tests" / "keys.test.ts").write_text(
            'const KEY = "sk-1234567890abcdef1234567890abcdef";\n', encoding="utf-8"
        )
        for args in (
            ["git", "init", "-q"],
            ["git", "add", "."],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        ):
            subprocess.run(args, cwd=remote, check=True)
        return remote

    def test_auto_scope_excludes_ts_test_secrets(self, tmp_path):
        # Auto-scoped to src/ (the only dir registering a tool): the fake key in
        # tests/ is never scanned.
        remote = self._ts_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        payload = json.loads(_invoke("scan", url, "-f", "json").stdout)
        assert "MCP102" not in {f["rule_id"] for f in payload["findings"]}

    def test_force_scope_tests_finds_the_secret(self, tmp_path):
        remote = self._ts_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        payload = json.loads(_invoke("scan", url, "--scope", "tests", "-f", "json").stdout)
        assert "MCP102" in {f["rule_id"] for f in payload["findings"]}

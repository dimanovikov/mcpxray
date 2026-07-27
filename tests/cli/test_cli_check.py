"""End-to-end CLI tests for the `check` command (friendly verdict card)."""

from __future__ import annotations

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

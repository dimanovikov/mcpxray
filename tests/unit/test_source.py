"""Unit tests for the source resolver (URL / local path / manifest)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mcpscore.source import SourceError, is_url, resolve_target


class TestIsUrl:
    def test_https(self):
        assert is_url("https://github.com/owner/repo")

    def test_http(self):
        assert is_url("http://github.com/owner/repo")

    def test_bare_github_host(self):
        assert is_url("github.com/owner/repo")

    def test_ssh_scp_style(self):
        assert is_url("git@github.com:owner/repo.git")

    def test_file_scheme(self):
        assert is_url("file:///C:/dev/repo")

    def test_local_path_is_not_url(self):
        assert not is_url("./some/dir")
        assert not is_url("some/dir/server.py")


class TestResolveLocal:
    def test_none_is_cwd(self):
        assert resolve_target(None, None).path == Path.cwd()

    def test_dot_is_cwd(self):
        assert resolve_target(".", None).path == Path.cwd()

    def test_existing_path_passthrough(self, tmp_path):
        r = resolve_target(str(tmp_path), None)
        assert r.path == tmp_path
        assert r.cleanup is None

    def test_missing_path_raises(self):
        with pytest.raises(SourceError, match="path not found"):
            resolve_target("no_such_path_xyz", None)

    def test_manifest_passthrough(self, tmp_path):
        m = tmp_path / "dump.json"
        m.write_text("{}", encoding="utf-8")
        r = resolve_target(None, m)
        assert r.manifest == m
        assert r.path is None


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
class TestResolveUrl:
    @staticmethod
    def _make_remote(parent: Path) -> Path:
        remote = parent / "remote"
        remote.mkdir()
        (remote / "server.py").write_text("# a clean server\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=remote, check=True)
        subprocess.run(["git", "add", "."], cwd=remote, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
            cwd=remote,
            check=True,
        )
        return remote

    def test_clones_local_file_repo(self, tmp_path):
        remote = self._make_remote(tmp_path)
        url = f"file:///{remote.as_posix()}"
        r = resolve_target(url, None)
        try:
            assert r.path is not None
            assert r.cleanup is not None
            assert (r.path / "server.py").exists()
            assert r.path != remote  # a clone, not a passthrough
        finally:
            if r.cleanup is not None:
                r.cleanup.cleanup()

    def test_clone_failure_raises(self):
        with pytest.raises(SourceError, match="could not clone"):
            resolve_target("file:///no/such/repo/anywhere_xyz", None)

    def test_missing_git_raises(self, monkeypatch):
        monkeypatch.setattr("mcpscore.source.shutil.which", lambda _: None)
        with pytest.raises(SourceError, match="git is not installed"):
            resolve_target("https://github.com/owner/repo", None)

    def test_clone_timeout_raises(self, monkeypatch):
        def _boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=1)

        monkeypatch.setattr("mcpscore.source.subprocess.run", _boom)
        with pytest.raises(SourceError, match="timed out"):
            resolve_target("https://github.com/owner/repo", None)

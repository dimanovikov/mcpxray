"""Resolve a CLI target (URL / local path / manifest) to a local source.

The friendly ``check`` command accepts a GitHub-style URL and clones it into a
temporary directory so the existing Python extractor can run over it — no new
dependencies, just ``git`` on the PATH and the standard library. URL handling
lives here (not under :mod:`mcpscore.extract`) because cloning is a transport
concern, not extraction: extractors build an IR from an already-local path.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Hosts we treat as remote VCS URLs even without an http(s):// scheme.
_VCS_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")

# Schemes ``git clone`` understands. ``file`` is included so tests (and local
# clones) work without touching the network.
_URL_SCHEMES = ("http", "https", "ssh", "git", "file")

# Defensive upper bound on a clone so a bad network can't hang CI/tests.
CLONE_TIMEOUT = 120


class SourceError(Exception):
    """Raised when a target cannot be resolved to a local path or manifest."""


@dataclass
class ResolvedSource:
    """Where to analyze from, plus an optional tempdir to clean up afterwards."""

    path: Path | None
    manifest: Path | None
    cleanup: tempfile.TemporaryDirectory | None  # set only when we cloned a URL


def is_url(arg: str) -> bool:
    """True if ``arg`` looks like a remote VCS URL.

    Covers ``http(s)://``, ``ssh://``, ``git://``, ``file://``, the SCP-style
    ``git@host:owner/repo``, and bare host prefixes (``github.com/owner/repo``).
    """
    if "://" in arg:
        return urlparse(arg).scheme.lower() in _URL_SCHEMES
    if arg.startswith("git@"):  # git@github.com:owner/repo.git
        return True
    return any(arg.startswith(host + "/") or arg.startswith(host + ":") for host in _VCS_HOSTS)


def _normalize_url(arg: str) -> str:
    """Add an ``https://`` scheme to bare host URLs (``github.com/...``)."""
    if "://" not in arg and not arg.startswith("git@"):
        return f"https://{arg}"
    return arg


def _clone(url: str) -> tuple[Path, tempfile.TemporaryDirectory]:
    """Shallow-clone ``url`` into a fresh temp directory; raise ``SourceError`` on failure."""
    if not shutil.which("git"):
        raise SourceError("git is not installed; install git or point mcpscore at a local path")
    tmp = tempfile.TemporaryDirectory(prefix="mcpscore-")
    # Clone into a subdir named after the repo so the verdict card shows a
    # readable name ("python-sdk") instead of the tempdir's random suffix.
    dest = Path(tmp.name) / _repo_name(url)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        tmp.cleanup()
        detail = (e.stderr or "").strip() or "unknown error"
        raise SourceError(f"could not clone {url}: {detail}") from e
    except subprocess.TimeoutExpired as e:
        tmp.cleanup()
        raise SourceError(f"timed out cloning {url} after {CLONE_TIMEOUT}s") from e
    except Exception as e:  # FileNotFoundError (git vanished), OSError, etc.
        tmp.cleanup()
        raise SourceError(f"could not clone {url}: {e}") from e
    return dest, tmp


def _repo_name(url: str) -> str:
    """Last path segment of a URL, ``.git`` stripped: ``…/owner/repo.git`` → ``repo``."""
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repo"


def resolve_target(arg: str | None, manifest: Path | None) -> ResolvedSource:
    """Resolve a CLI target into a local path/manifest (+ optional tempdir).

    * ``manifest`` wins — pass it straight through (existence is validated later).
    * ``None``/``"."`` → the current working directory.
    * a URL → shallow-cloned into a temp directory (caller cleans ``cleanup`` up).
    * anything else → treated as a local path (must exist).
    """
    if manifest is not None:
        return ResolvedSource(path=None, manifest=manifest, cleanup=None)

    if arg is None or arg == ".":
        return ResolvedSource(path=Path.cwd(), manifest=None, cleanup=None)

    if is_url(arg):
        path, cleanup = _clone(_normalize_url(arg))
        return ResolvedSource(path=path, manifest=None, cleanup=cleanup)

    local = Path(arg)
    if not local.exists():
        raise SourceError(f"path not found: {arg}")
    return ResolvedSource(path=local, manifest=None, cleanup=None)

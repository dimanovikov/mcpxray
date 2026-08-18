"""Resolve a CLI target (URL / local path / manifest) to a local source.

The friendly ``check`` command accepts a GitHub-style URL and clones it into a
temporary directory so the existing Python extractor can run over it — no new
dependencies, just ``git`` on the PATH and the standard library. URL handling
lives here (not under :mod:`mcpxray.extract`) because cloning is a transport
concern, not extraction: extractors build an IR from an already-local path.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from mcpxray.extract.python_static import _PY_EXTS, _iter_source_files
from mcpxray.extract.typescript_static import _TS_EXTS

# Combined source extensions so scope detection narrows a TS repo the same way
# it already narrows a Python one (rather than scanning it wholesale).
_SOURCE_EXTS = _PY_EXTS + _TS_EXTS

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

    path: Path | None  # scan scope: the tree walked for source (may be a subdir)
    root: Path | None  # project root for pyproject/lockfiles (== path unless narrowed)
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
        raise SourceError("git is not installed; install git or point mcpxray at a local path")
    tmp = tempfile.TemporaryDirectory(prefix="mcpxray-")
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


# --- scope: locate the *server* source inside a tree -------------------------

# A cheap textual signal for an MCP tool registration/decorator. Catches the
# Python decorator (``@mcp.tool()``), the high-level registration call
# (``server.tool(...)`` / ``server.registerTool(...)``) used by both SDKs, and the
# low-level TS handler anchor (``ListToolsRequestSchema``) — good enough to bucket
# files by directory for the scope heuristic.
_TOOL_RE = re.compile(
    r"\.\s*(?:tool|registerTool)\s*\(" r"|ListToolsRequestSchema" r"|^\s*@tool\b",
    re.MULTILINE,
)


def _has_source(path: Path) -> bool:
    """True if ``path`` contains any Python or TypeScript source (a coarse "is code" signal)."""
    return any(True for _ in _iter_source_files(path, _SOURCE_EXTS))


def _has_tool_call(path: Path) -> bool:
    """True if any source file under ``path`` registers an MCP tool."""
    for p in _iter_source_files(path, _SOURCE_EXTS):
        try:
            if _TOOL_RE.search(p.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def _entry_from_scripts(root: Path) -> Path | None:
    """Derive the server dir from ``[project.scripts]`` (only if it also has tools).

    Maps each ``"pkg.mod:attr"`` entry point to ``root/src/<topseg>`` or
    ``root/<topseg>`` and returns the first existing dir that also registers a
    tool — so a library's CLI entry point never narrows us into a tool-less dir.
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None
    scripts = dict((data.get("project") or {}).get("scripts") or {})
    scripts.update(((data.get("tool") or {}).get("poetry") or {}).get("scripts") or {})
    for entry in scripts.values():
        if not isinstance(entry, str) or ":" not in entry:
            continue
        top = entry.split(":", 1)[0].split(".")[0]
        for cand in (root / "src" / top, root / top):
            if cand.is_dir() and _has_tool_call(cand):
                return cand
    return None


def _entry_from_tools(root: Path) -> Path | None:
    """The immediate subdirectory of ``root`` holding the most tool registrations."""
    counts: dict[Path, int] = {}
    for f in _iter_source_files(root, _SOURCE_EXTS):
        try:
            n = len(_TOOL_RE.findall(f.read_text(encoding="utf-8")))
        except OSError:
            continue
        if n == 0:
            continue
        rel = f.relative_to(root).parts
        if len(rel) < 2:
            continue  # file sits directly under root — narrowing would be a no-op
        bucket = root / rel[0]
        counts[bucket] = counts.get(bucket, 0) + n
    if not counts:
        return None
    return max(counts, key=counts.get)


def _detect_entry_dir(root: Path) -> Path:
    """Best-effort locate the server source dir within ``root``; fall back to ``root``.

    Order: ``[project.scripts]`` entry point → the immediate subdir with the most
    tool registrations → ``src/`` (if it holds any source) → ``root``. Only
    narrows to a strict subdirectory on positive evidence, so an ambiguous tree is
    scanned wholesale (current behaviour) rather than wrongly narrowed.
    """
    return (
        _entry_from_scripts(root)
        or _entry_from_tools(root)
        or ((root / "src") if (root / "src").is_dir() and _has_source(root / "src") else None)
        or root
    )


def _scope_path(root: Path, override: str | None) -> Path:
    """Resolve the scan scope within ``root``: an explicit override, else auto-detect."""
    if override:
        candidate = root / override
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            raise SourceError(f"--scope must stay under the target: {override!r}") from None
        if not candidate.is_dir():
            raise SourceError(f"--scope is not a directory under the target: {override!r}")
        return candidate
    return _detect_entry_dir(root)


def resolve_target(
    arg: str | None, manifest: Path | None, scope: str | None = None
) -> ResolvedSource:
    """Resolve a CLI target into a local path/manifest (+ optional tempdir).

    * ``manifest`` wins — pass it straight through (existence is validated later).
    * ``None``/``"."`` → the current working directory (scanned literally, no scope).
    * a URL → shallow-cloned into a temp directory (caller cleans ``cleanup`` up),
      then narrowed to the server source dir unless ``scope`` says otherwise.
    * anything else → treated as a local path (must exist); a directory is narrowed
      to the server source dir unless ``scope`` says otherwise.

    ``ResolvedSource.path`` is the *scan scope* (possibly a subdir of ``root``);
    ``ResolvedSource.root`` is the project root used for ``pyproject.toml`` /
    lockfiles, so dependency checks survive scope narrowing.
    """
    if manifest is not None:
        return ResolvedSource(path=None, root=None, manifest=manifest, cleanup=None)

    if arg is None or arg == ".":
        cwd = Path.cwd()
        return ResolvedSource(path=cwd, root=cwd, manifest=None, cleanup=None)

    if is_url(arg):
        clone_root, cleanup = _clone(_normalize_url(arg))
        scope_dir = _scope_path(clone_root, scope) if clone_root.is_dir() else clone_root
        return ResolvedSource(path=scope_dir, root=clone_root, manifest=None, cleanup=cleanup)

    local = Path(arg)
    if not local.exists():
        raise SourceError(f"path not found: {arg}")
    if local.is_dir():
        scope_dir = _scope_path(local, scope)
        return ResolvedSource(path=scope_dir, root=local, manifest=None, cleanup=None)
    return ResolvedSource(path=local, root=local, manifest=None, cleanup=None)

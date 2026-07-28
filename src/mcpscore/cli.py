"""mcpscore CLI — `scan`, `score`, `badge`, `version`.

The CLI is a thin shell over the extractor → rule-engine → score → render
pipeline. `scan` lints and reports; `score` collapses to a 0-100 number;
`badge` emits an SVG; `version` prints the version.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from mcpscore import __version__
from mcpscore.badge import badge_svg
from mcpscore.extract import extractor_for
from mcpscore.extract.manifest import ManifestExtractor
from mcpscore.extract.manifest import from_tools as manifest_from_tools
from mcpscore.ir import SEVERITY_ERROR, SOURCE_STATIC, McpServer, ServerMeta
from mcpscore.report import SUPPORTED_FORMATS, render
from mcpscore.report.card import render_verdict
from mcpscore.rules import run_all
from mcpscore.runtime import CaptureError, capture_tools, split_command
from mcpscore.score import ScoreResult
from mcpscore.score import score as score_doc
from mcpscore.source import ResolvedSource, SourceError, resolve_target
from mcpscore.verdict import verdict

app = typer.Typer(
    name="mcpscore",
    help="Static linter + 0-100 scorecard for MCP servers.",
    no_args_is_help=True,
    add_completion=False,
)


def _extract_doc(
    resolved: ResolvedSource, runtime_argv: list[str] | None, *, graceful: bool
) -> McpServer:
    """Build a :class:`McpServer` from a manifest file, a runtime capture, or source.

    The three input modes are mutually exclusive (enforced in :func:`_run`).
    ``graceful`` only affects the static no-extractor case: ``check`` synthesizes
    an empty static doc (→ an honest UNKNOWN card); ``scan``/``score`` exit-2.
    """
    if resolved.manifest is not None:
        if not resolved.manifest.is_file():
            typer.echo(f"error: manifest not found: {resolved.manifest}", err=True)
            raise typer.Exit(code=2)
        return ManifestExtractor().extract(resolved.manifest)

    if runtime_argv is not None:
        captured = capture_tools(runtime_argv, cwd=resolved.path)
        return manifest_from_tools(
            captured.tools,
            name=captured.server_name or "runtime",
            path_str=str(resolved.path or resolved.root or Path.cwd()),
            version=captured.server_version,
        )

    path = resolved.path if resolved.path is not None else Path.cwd()
    extractor = extractor_for(path)
    if extractor is None:
        if graceful:
            return McpServer(
                meta=ServerMeta(name=path.name, language=None, path=str(resolved.root or path)),
                source_mode=SOURCE_STATIC,
            )
        typer.echo(
            f"error: no extractor matched {path} "
            "(point at a source tree, pass --manifest <tools/list.json>, "
            "or use --runtime --command '<launch>')",
            err=True,
        )
        raise typer.Exit(code=2)
    return extractor.extract(path, root=resolved.root)


def _analyze(
    resolved: ResolvedSource, runtime_argv: list[str] | None, *, graceful: bool
) -> tuple[McpServer, ScoreResult]:
    """Extract, run all rules, score. Returns (doc, score_result)."""
    doc = _extract_doc(resolved, runtime_argv, graceful=graceful)
    run_all(doc)
    return doc, score_doc(doc)


def _run(
    target: str | None,
    manifest: Path | None,
    scope: str | None,
    runtime: bool,
    command: str | None,
    *,
    graceful: bool,
) -> tuple[McpServer, ScoreResult]:
    """Resolve a target (URL / path / manifest, optionally scoped) and analyze it.

    Shared by every command so URL input, ``--scope``, ``--runtime``, and tempdir
    cleanup live in one place. ``graceful`` selects UNKNOWN-on-no-extractor
    (``check``) vs the exit-2 that ``scan``/``score``/``badge`` raise.
    """
    if manifest is not None and runtime:
        typer.echo("error: --manifest and --runtime are mutually exclusive", err=True)
        raise typer.Exit(code=2)
    if runtime and not command:
        typer.echo("error: --runtime needs --command <launch cmd>", err=True)
        raise typer.Exit(code=2)

    resolved: ResolvedSource | None = None
    try:
        runtime_argv = split_command(command) if runtime else None
        resolved = resolve_target(target, manifest, scope)
        return _analyze(resolved, runtime_argv, graceful=graceful)
    except CaptureError as e:
        typer.echo(f"error: runtime capture failed: {e}", err=True)
        raise typer.Exit(code=2) from None
    finally:
        if resolved is not None and resolved.cleanup is not None:
            try:
                resolved.cleanup.cleanup()
            except OSError:  # git may briefly hold pack-locks on Windows
                shutil.rmtree(resolved.cleanup.name, ignore_errors=True)


@app.command()
def check(
    target: str = typer.Argument(None, help="GitHub URL or local path to the MCP server source."),
    manifest: Path = typer.Option(
        None, "--manifest", help="Captured tools/list JSON dump instead of source/URL."
    ),
    runtime: bool = typer.Option(
        False,
        "--runtime",
        help=(
            "Spawn the server and capture its tools/list over MCP stdio (opt-in; "
            "needs --command; executes the server — trusted/container only)."
        ),
    ),
    command: str = typer.Option(
        None,
        "--command",
        help="Launch command for --runtime, e.g. 'python -m srv' / 'node server.js' (POSIX split).",
    ),
    scope: str = typer.Option(
        None, "--scope", help="Subdirectory to scan/run in, relative to the target."
    ),
    details: bool = typer.Option(
        False, "--details", "-v", help="Also print the full finding list."
    ),
    fail_under: int = typer.Option(
        0, "--fail-under", help="Gate: exit 1 if the score is below N (CI mode)."
    ),
) -> None:
    """Friendly safety check: is this MCP server safe to install?"""
    try:
        doc, score_result = _run(target, manifest, scope, runtime, command, graceful=True)
    except SourceError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2) from None

    v = verdict(doc, score_result)
    typer.echo(render_verdict(v, doc=doc, score_result=score_result, details=details))

    if v.tier == "danger" or not score_result.passed(fail_under):
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the mcpscore version."""
    typer.echo(__version__)


@app.command()
def scan(
    target: str = typer.Argument(None, help="Path or URL to the MCP server source."),
    manifest: Path = typer.Option(
        None, "--manifest", help="Captured tools/list JSON dump instead of source."
    ),
    runtime: bool = typer.Option(
        False,
        "--runtime",
        help=(
            "Spawn the server and capture its tools/list over MCP stdio (opt-in; needs --command)."
        ),
    ),
    command: str = typer.Option(
        None,
        "--command",
        help="Launch command for --runtime, e.g. 'python -m srv' / 'node server.js'.",
    ),
    scope: str = typer.Option(
        None, "--scope", help="Subdirectory to scan/run in, relative to the target."
    ),
    fmt: str = typer.Option(
        "plain", "-f", "--format", help=f"Report format: {', '.join(SUPPORTED_FORMATS)}."
    ),
    check: bool = typer.Option(
        False, "--check", help="Gate: exit 1 on any ERROR finding (CI mode)."
    ),
) -> None:
    """Lint an MCP server and print findings in the chosen format."""
    try:
        doc, score_result = _run(target, manifest, scope, runtime, command, graceful=False)
    except SourceError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(render(doc.diagnostics, fmt, doc=doc, score_result=score_result))
    if check and any(d.severity == SEVERITY_ERROR for d in doc.diagnostics):
        raise typer.Exit(code=1)


@app.command()
def score(
    target: str = typer.Argument(None, help="Path or URL to the MCP server source."),
    manifest: Path = typer.Option(None, "--manifest", help="Captured tools/list JSON dump."),
    runtime: bool = typer.Option(
        False,
        "--runtime",
        help=(
            "Spawn the server and capture its tools/list over MCP stdio (opt-in; needs --command)."
        ),
    ),
    command: str = typer.Option(
        None,
        "--command",
        help="Launch command for --runtime, e.g. 'python -m srv' / 'node server.js'.",
    ),
    scope: str = typer.Option(
        None, "--scope", help="Subdirectory to scan/run in, relative to the target."
    ),
    fail_under: int = typer.Option(0, "--fail-under", help="Gate: exit 1 if the score is below N."),
) -> None:
    """Print the 0-100 score and grade; exit 1 if below --fail-under."""
    try:
        _doc, score_result = _run(target, manifest, scope, runtime, command, graceful=False)
    except SourceError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2) from None
    cap = "  [capped by error finding]" if score_result.capped else ""
    typer.echo(f"score {score_result.score}/100 (grade {score_result.grade}){cap}")
    if not score_result.passed(fail_under):
        raise typer.Exit(code=1)


@app.command()
def badge(
    target: str = typer.Argument(None, help="Path or URL to the MCP server source to score."),
    score_value: int = typer.Option(None, "--score", help="Render a literal score (0-100)."),
    output: Path = typer.Option(
        Path("badge.svg"), "-o", "--output", help="Output SVG path ('-' for stdout)."
    ),
) -> None:
    """Render a score badge as SVG (from a path/URL, or a literal --score)."""
    if score_value is not None:
        result = ScoreResult(score=score_value, errors=0, warnings=0, infos=0, capped=False)
    elif target is not None:
        try:
            _doc, result = _run(target, None, None, False, None, graceful=False)
        except SourceError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=2) from None
    else:
        typer.echo("error: provide a PATH or --score N", err=True)
        raise typer.Exit(code=2)

    svg = badge_svg(result)
    if str(output) == "-":
        typer.echo(svg)
    else:
        output.write_text(svg, encoding="utf-8")
        typer.echo(f"wrote {output}")


if __name__ == "__main__":
    app()

"""mcpscore CLI — `scan`, `score`, `badge`, `version`.

The CLI is a thin shell over the extractor → rule-engine → score → render
pipeline. `scan` lints and reports; `score` collapses to a 0-100 number;
`badge` emits an SVG; `version` prints the version.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mcpscore import __version__
from mcpscore.badge import badge_svg
from mcpscore.extract import extractor_for
from mcpscore.extract.manifest import ManifestExtractor
from mcpscore.ir import SEVERITY_ERROR, McpServer
from mcpscore.report import SUPPORTED_FORMATS, render
from mcpscore.rules import run_all
from mcpscore.score import ScoreResult
from mcpscore.score import score as score_doc

app = typer.Typer(
    name="mcpscore",
    help="Static linter + 0-100 scorecard for MCP servers.",
    no_args_is_help=True,
    add_completion=False,
)


def _extract(path: Path | None, manifest: Path | None) -> McpServer:
    """Build a :class:`McpServer` IR from a source path or a manifest dump."""
    if manifest is not None:
        if not manifest.is_file():
            typer.echo(f"error: manifest not found: {manifest}", err=True)
            raise typer.Exit(code=2)
        return ManifestExtractor().extract(manifest)

    target = path if path is not None and str(path) != "." else Path.cwd()
    extractor = extractor_for(target)
    if extractor is None:
        typer.echo(
            f"error: no extractor matched {target} "
            "(point at a Python source tree, or pass --manifest <tools/list.json>)",
            err=True,
        )
        raise typer.Exit(code=2)
    return extractor.extract(target)


def _analyze(path: Path | None, manifest: Path | None) -> tuple[McpServer, ScoreResult]:
    """Extract, run all rules, score. Returns (doc, score_result)."""
    doc = _extract(path, manifest)
    run_all(doc)
    return doc, score_doc(doc)


@app.command()
def version() -> None:
    """Print the mcpscore version."""
    typer.echo(__version__)


@app.command()
def scan(
    path: Path = typer.Argument(None, help="Path to the MCP server source."),
    manifest: Path = typer.Option(
        None, "--manifest", help="Captured tools/list JSON dump instead of source."
    ),
    fmt: str = typer.Option(
        "plain", "-f", "--format", help=f"Report format: {', '.join(SUPPORTED_FORMATS)}."
    ),
    check: bool = typer.Option(
        False, "--check", help="Gate: exit 1 on any ERROR finding (CI mode)."
    ),
) -> None:
    """Lint an MCP server and print findings in the chosen format."""
    doc, score_result = _analyze(path, manifest)
    typer.echo(render(doc.diagnostics, fmt, doc=doc, score_result=score_result))
    if check and any(d.severity == SEVERITY_ERROR for d in doc.diagnostics):
        raise typer.Exit(code=1)


@app.command()
def score(
    path: Path = typer.Argument(None, help="Path to the MCP server source."),
    manifest: Path = typer.Option(None, "--manifest", help="Captured tools/list JSON dump."),
    fail_under: int = typer.Option(0, "--fail-under", help="Gate: exit 1 if the score is below N."),
) -> None:
    """Print the 0-100 score and grade; exit 1 if below --fail-under."""
    _doc, score_result = _analyze(path, manifest)
    cap = "  [capped by error finding]" if score_result.capped else ""
    typer.echo(f"score {score_result.score}/100 (grade {score_result.grade}){cap}")
    if not score_result.passed(fail_under):
        raise typer.Exit(code=1)


@app.command()
def badge(
    path: Path = typer.Argument(None, help="Path to the MCP server source to score."),
    score_value: int = typer.Option(None, "--score", help="Render a literal score (0-100)."),
    output: Path = typer.Option(
        Path("badge.svg"), "-o", "--output", help="Output SVG path ('-' for stdout)."
    ),
) -> None:
    """Render a score badge as SVG (from a path, or a literal --score)."""
    if score_value is not None:
        result = ScoreResult(score=score_value, errors=0, warnings=0, infos=0, capped=False)
    elif path is not None:
        _doc, result = _analyze(path, None)
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

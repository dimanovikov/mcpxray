"""mcpscore CLI.

v0.0.0 ships a working `version` plus command stubs. The real `scan` / `score`
/ `badge` land in v0.1 alongside the extractor + rule engine.
"""

from __future__ import annotations

import typer

from mcpscore import __version__

app = typer.Typer(
    name="mcpscore",
    help="Static linter + 0-100 scorecard for MCP servers.",
    no_args_is_help=True,
    add_completion=False,
)


def _v01(cmd: str) -> None:
    """Stub for commands that ship in v0.1."""
    typer.echo(f"mcpscore {cmd}: coming in v0.1 (currently v{__version__}).")
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the mcpscore version."""
    typer.echo(__version__)


@app.command()
def scan(
    path: str = typer.Argument(None, help="Path to the MCP server source."),
    manifest: str = typer.Option(None, "--manifest", help="Captured tools/list JSON."),
    fmt: str = typer.Option("plain", "-f", "--format", help="plain|json|github|sarif"),
    check: bool = typer.Option(False, "--check", help="Exit 1 on any ERROR."),
) -> None:
    """Lint an MCP server; exit 1 on any ERROR (v0.1)."""
    _v01("scan")


@app.command()
def score(
    path: str = typer.Argument(None, help="Path to the MCP server source."),
    fail_under: int = typer.Option(0, "--fail-under", help="Exit 1 if score < N."),
) -> None:
    """Print the 0-100 score; exit 1 under threshold (v0.1)."""
    _v01("score")


@app.command()
def badge(
    value: int = typer.Option(..., "--score", help="Score to render."),
    output: str = typer.Option("badge.svg", "-o", "--output", help="Output SVG path."),
) -> None:
    """Render a score badge as SVG (v0.1)."""
    _v01("badge")


if __name__ == "__main__":
    app()

"""Report formatters: plain, json, github, sarif.

Every formatter shares the signature ``render(diags, doc, score_result) -> str``
so the CLI can dispatch by name. ``doc`` and ``score_result`` are optional;
formatters include the score line only when a :class:`~mcpscore.score.ScoreResult`
is supplied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcpscore.report import card as card_fmt
from mcpscore.report import github as github_fmt
from mcpscore.report import json as json_fmt
from mcpscore.report import plain, sarif

if TYPE_CHECKING:
    from mcpscore.ir import Diagnostic, McpServer
    from mcpscore.score import ScoreResult

_FORMATTERS = {
    "plain": plain.render,
    "json": json_fmt.render,
    "github": github_fmt.render,
    "sarif": sarif.render,
    "card": card_fmt.render,
}

SUPPORTED_FORMATS = tuple(_FORMATTERS)


def render(
    diags: list[Diagnostic],
    fmt: str,
    *,
    doc: McpServer | None = None,
    score_result: ScoreResult | None = None,
) -> str:
    """Render diagnostics in the requested format."""
    try:
        formatter = _FORMATTERS[fmt.lower()]
    except KeyError as e:
        raise ValueError(
            f"unknown format {fmt!r}; choose from {', '.join(SUPPORTED_FORMATS)}"
        ) from e
    return formatter(diags, doc, score_result)

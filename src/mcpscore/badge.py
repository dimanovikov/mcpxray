"""Score badge as an SVG (shields-style, embeddable in a README)."""

from __future__ import annotations

from mcpscore.score import ScoreResult

_GRADE_COLOR = {
    "A": "#4c1",  # brightgreen
    "B": "#97ca00",  # green
    "C": "#dfb317",  # yellow
    "D": "#fe7d37",  # orange
    "F": "#e05d44",  # red
}

_HEIGHT = 20
_FONT = "Verdana, 'DejaVu Sans', sans-serif"
_FONT_SIZE = 11
_CHAR_WIDTH = 6.2  # approx average advance for the badge font at size 11
_PAD = 6


def _text_width(text: str) -> int:
    return int(len(text) * _CHAR_WIDTH) + 2 * _PAD


def badge_svg(score_result: ScoreResult, *, label: str = "mcp score") -> str:
    """Render a flat SVG badge for the given score."""
    color = _GRADE_COLOR[score_result.grade]
    value = f"{score_result.score}/100"
    label_w = _text_width(label)
    value_w = _text_width(value)
    total_w = label_w + value_w

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{total_w}" height="{_HEIGHT}"'
        f' role="img" aria-label="{label}: {value}">'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<rect width="{total_w}" height="{_HEIGHT}" fill="#555"/>'
        f'<rect x="{label_w}" width="{value_w}" height="{_HEIGHT}" fill="{color}"/>'
        f'<rect width="{total_w}" height="{_HEIGHT}" fill="url(#s)"/>'
        f'<text x="{_PAD}" y="14" fill="#fff" font-family="{_FONT}" font-size="{_FONT_SIZE}">'
        f"{label}</text>"
        f'<text x="{label_w + _PAD}" y="14" fill="#fff" font-family="{_FONT}"'
        f' font-size="{_FONT_SIZE}">{value}</text>'
        f"</svg>"
    )

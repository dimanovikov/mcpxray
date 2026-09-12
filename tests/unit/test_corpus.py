"""Extraction must keep working on shapes taken from published servers.

Synthetic fixtures written alongside an extractor tend to test what it already
does. These come from real servers, so they fail when reality moves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcpxray.extract.python_static import PythonExtractor

CORPUS = Path(__file__).parent.parent / "fixtures" / "corpus"


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("lowlevel_literal_server.py", {"fetch"}),
        (
            "lowlevel_enum_server.py",
            {"git_status", "git_diff_unstaged", "git_commit"},
        ),
    ],
)
def test_published_server_shapes_still_extract(tmp_path: Path, fixture: str, expected: set[str]):
    (tmp_path / "server.py").write_text(
        (CORPUS / fixture).read_text(encoding="utf-8"), encoding="utf-8"
    )
    doc = PythonExtractor().extract(tmp_path)
    assert {t.name for t in doc.tools} == expected


def test_a_model_built_schema_is_marked_unresolved(tmp_path: Path):
    """Rules must be able to tell "no schema" from "a schema we could not read"."""
    (tmp_path / "server.py").write_text(
        (CORPUS / "lowlevel_enum_server.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    doc = PythonExtractor().extract(tmp_path)
    assert all(t.schema_unresolved for t in doc.tools)

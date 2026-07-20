"""Unit tests for the builtin rules — one fixture per rule, plus ordering/clean."""

from __future__ import annotations

from pathlib import Path

from mcpscore.extract import extractor_for
from mcpscore.rules import run_all

FIXTURES = Path(__file__).parent.parent / "fixtures" / "servers"


def _run(path: Path):
    ext = extractor_for(path)
    assert ext is not None, f"no extractor for {path}"
    doc = ext.extract(path)
    diags = run_all(doc)
    return [d.rule_id for d in diags], doc


class TestRules:
    def test_clean_has_no_findings(self):
        ids, _ = _run(FIXTURES / "clean")
        assert ids == []

    def test_mcp101_poisoning(self):
        ids, _ = _run(FIXTURES / "poisoned")
        assert "MCP101" in ids

    def test_mcp102_secrets_and_mcp103_rce(self):
        ids, doc = _run(FIXTURES / "leaky")
        assert "MCP102" in ids
        assert "MCP103" in ids
        # findings carry a source location
        assert any(d.file and d.line for d in doc.diagnostics)

    def test_mcp107_missing_description(self):
        ids, _ = _run(FIXTURES / "bare")
        assert ids == ["MCP107"]

    def test_mcp108_unpinned_deps(self):
        ids, doc = _run(FIXTURES / "unpinned")
        assert "MCP108" in ids
        assert doc.dependencies  # extractor parsed pyproject

    def test_mcp104_weak_and_mcp106_incompat_schema(self):
        ids, _ = _run(FIXTURES / "weak_schema.json")
        assert "MCP104" in ids
        assert "MCP106" in ids

    def test_findings_sorted_errors_first(self):
        ids, _ = _run(FIXTURES / "leaky")
        assert ids[0] in ("MCP102", "MCP103")  # both are ERROR severity

    def test_diagnostics_mirrored_to_doc(self):
        _, doc = _run(FIXTURES / "poisoned")
        assert doc.has_errors
        assert doc.errors  # property returns the error list

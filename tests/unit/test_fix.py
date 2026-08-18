"""Unit tests for the auto-fix engine (``mcpxray.fix``) and MCP108's ``Fix``."""

from __future__ import annotations

from pathlib import Path

from mcpxray.extract import extractor_for
from mcpxray.fix import (
    ApplySummary,
    _apply_edits,
    apply_fixes,
    exact_pin,
    has_pending,
    pin_floor,
    plan_fixes,
    render_diff,
)
from mcpxray.ir import Diagnostic, Fix, McpServer, ServerMeta, TextEdit
from mcpxray.rules import run_all

FIXTURES = Path(__file__).parent.parent / "fixtures" / "servers"


# --- pure helpers -----------------------------------------------------------


class TestPinFloor:
    def test_extracts_full_floor_from_floating_specs(self):
        assert pin_floor("^1.2.3") == "1.2.3"
        assert pin_floor("~1.2.3") == "1.2.3"
        assert pin_floor(">=1.2.3") == "1.2.3"
        assert pin_floor("=1.2.3") == "1.2.3"
        assert pin_floor("v1.2.3") == "1.2.3"

    def test_keeps_pre_release_and_build_suffix(self):
        assert pin_floor("^1.2.3-beta.1") == "1.2.3-beta.1"
        assert pin_floor(">=1.2.3+build.7") == "1.2.3+build.7"

    def test_none_when_no_full_floor(self):
        # major-only range, wildcards, tags, bare names, x-ranges → unresolvable
        for spec in (">=2", "*", "latest", "flask", "1.x", "1.2.x", ""):
            assert pin_floor(spec) is None


class TestExactPin:
    def test_pip_prefixes_double_equals(self):
        assert exact_pin(">=2.30.0", pip=True) == "==2.30.0"

    def test_npm_is_bare_version(self):
        assert exact_pin("^1.2.3", pip=False) == "1.2.3"

    def test_none_when_unresolvable(self):
        assert exact_pin("*", pip=True) is None
        assert exact_pin("flask", pip=False) is None


# --- edit application -------------------------------------------------------


class TestApplyEdits:
    def test_unique_literal_replace(self):
        out, applied, skipped = _apply_edits(
            "a requests>=2.30.0 b", [TextEdit(">=2.30.0", "==2.30.0")]
        )
        assert out == "a requests==2.30.0 b"
        assert applied == [TextEdit(">=2.30.0", "==2.30.0")]
        assert skipped == []

    def test_ambiguous_old_is_skipped(self):
        text = 'name: "1.2.3"\nother: "1.2.3"\n'
        out, applied, skipped = _apply_edits(text, [TextEdit('"1.2.3"', '"1.2.4"')])
        assert out == text  # unchanged
        assert applied == []
        assert any("ambiguous" in m for m in skipped)

    def test_missing_old_is_skipped(self):
        out, applied, skipped = _apply_edits("nothing here", [TextEdit("nope", "x")])
        assert out == "nothing here"
        assert applied == []
        assert any("not found" in m for m in skipped)

    def test_overlapping_edits_keep_first(self):
        text = "abcdef"
        # "bcd" (3..6) overlaps "cde" (2..5) after sort by start
        out, applied, skipped = _apply_edits(text, [TextEdit("cde", "CDE"), TextEdit("bcd", "BCD")])
        assert applied == [TextEdit("bcd", "BCD")]  # earlier start wins
        assert any("overlaps" in m for m in skipped)
        assert out == "aBCDef"

    def test_noop_edit_ignored(self):
        out, applied, _ = _apply_edits("x", [TextEdit("", "y"), TextEdit("a", "a")])
        assert out == "x"
        assert applied == []


# --- plan / diff / apply on temp files --------------------------------------


def _doc_with_fix(file_path: str) -> McpServer:
    doc = McpServer(meta=ServerMeta(name="t"))
    doc.diagnostics = [
        Diagnostic("MCP108", "warning", "unpinned", fix=Fix("pin deps", file_path, [])),
        Diagnostic("MCP104", "warning", "weak schema"),  # no fix → ignored
    ]
    return doc


class TestPlanFixes:
    def test_collects_only_fixes_and_groups_per_file(self):
        doc = McpServer(meta=ServerMeta(name="t"))
        doc.diagnostics = [
            Diagnostic("MCP108", "warning", "a", fix=Fix("p", "f1.toml", [TextEdit("a", "b")])),
            Diagnostic("MCP999", "warning", "b", fix=Fix("p", "f1.toml", [TextEdit("c", "d")])),
            Diagnostic("MCP104", "warning", "c"),  # no fix
            Diagnostic("MCP108", "warning", "d", fix=Fix("p", "f2.json", [TextEdit("e", "f")])),
        ]
        fixes = plan_fixes(doc)
        by_file = {f.file: f for f in fixes}
        assert set(by_file) == {"f1.toml", "f2.json"}
        assert [e.old for e in by_file["f1.toml"].edits] == ["a", "c"]
        assert [e.old for e in by_file["f2.json"].edits] == ["e"]

    def test_has_pending(self):
        assert not has_pending([Fix("p", "f", [])])
        assert has_pending([Fix("p", "f", [TextEdit("a", "b")])])


class TestRenderDiffAndApply:
    def test_diff_shows_changes_without_writing(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        original = '[project]\ndependencies = ["requests>=2.30.0"]\n'
        f.write_text(original, encoding="utf-8")
        doc = _doc_with_fix(str(f))
        doc.diagnostics[0].fix.edits.append(TextEdit("requests>=2.30.0", "requests==2.30.0"))

        diff = render_diff(plan_fixes(doc))
        assert "-dependencies = " in diff
        assert '+dependencies = ["requests==2.30.0"]' in diff or "requests==2.30.0" in diff
        # nothing written
        assert f.read_text(encoding="utf-8") == original

    def test_apply_writes_file_and_counts(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text(
            '[project]\ndependencies = ["requests>=2.30.0", "httpx>=0.27.0"]\n', encoding="utf-8"
        )
        doc = _doc_with_fix(str(f))
        doc.diagnostics[0].fix.edits = [
            TextEdit("requests>=2.30.0", "requests==2.30.0"),
            TextEdit("httpx>=0.27.0", "httpx==0.27.0"),
        ]
        summary = apply_fixes(plan_fixes(doc))
        assert isinstance(summary, ApplySummary)
        assert summary.files_changed == 1
        assert summary.edits_applied == 2
        assert summary.skipped == []
        text = f.read_text(encoding="utf-8")
        assert "requests==2.30.0" in text
        assert "httpx==0.27.0" in text
        assert ">=2.30.0" not in text

    def test_apply_leaves_no_temp_file(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('["requests>=2.30.0"]\n', encoding="utf-8")
        doc = _doc_with_fix(str(f))
        doc.diagnostics[0].fix.edits = [TextEdit(">=2.30.0", "==2.30.0")]
        apply_fixes(plan_fixes(doc))
        assert not (tmp_path / "pyproject.toml.mcpxray-tmp").exists()

    def test_apply_records_unreadable_file(self, tmp_path):
        doc = _doc_with_fix(str(tmp_path / "missing.toml"))
        doc.diagnostics[0].fix.edits = [TextEdit("a", "b")]
        summary = apply_fixes(plan_fixes(doc))
        assert summary.files_changed == 0
        assert any("unreadable" in m for m in summary.skipped)


# --- MCP108 actually attaches a Fix -----------------------------------------


class TestMCP108Fix:
    def _pyproject_server(self, tmp_path: Path, deps_line: str) -> McpServer:
        (tmp_path / "server.py").write_text(
            'from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("d")\n'
            '@mcp.tool()\ndef echo(v: str) -> str:\n    """e"""\n    return v\n',
            encoding="utf-8",
        )
        (tmp_path / "pyproject.toml").write_text(
            f'[project]\nname = "d"\nversion = "0"\ndependencies = {deps_line}\n', encoding="utf-8"
        )
        ext = extractor_for(tmp_path)
        assert ext is not None
        doc = ext.extract(tmp_path)
        run_all(doc)
        return doc

    def test_pip_fix_has_edits_for_full_floors_only(self, tmp_path):
        doc = self._pyproject_server(tmp_path, '["requests>=2.30.0", "httpx>=0.27.0", "flask"]')
        mcp108 = next(d for d in doc.diagnostics if d.rule_id == "MCP108")
        assert mcp108.fix is not None
        assert mcp108.fix.file == str(tmp_path / "pyproject.toml")
        pairs = {e.old: e.new for e in mcp108.fix.edits}
        assert pairs == {
            "requests>=2.30.0": "requests==2.30.0",
            "httpx>=0.27.0": "httpx==0.27.0",
        }  # bare ``flask`` has no floor → skipped

    def test_pip_no_floor_yields_no_fix(self, tmp_path):
        # The existing ``unpinned/`` shape: >=2 (major-only) + bare → nothing fixable.
        doc = self._pyproject_server(tmp_path, '["requests>=2", "flask"]')
        mcp108 = next(d for d in doc.diagnostics if d.rule_id == "MCP108")
        assert mcp108.fix is None

    def test_npm_fix_anchors_on_key_value_pair(self, tmp_path):
        (tmp_path / "server.ts").write_text(
            'const s = { tool: () => {} };\ns.tool("ping", "p", {}, async () => ({}));\n',
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"zod": "^3.0.0", "@modelcontextprotocol/sdk": "^1.0.0"}}\n',
            encoding="utf-8",
        )
        ext = extractor_for(tmp_path)
        doc = ext.extract(tmp_path)
        run_all(doc)
        mcp108 = next(d for d in doc.diagnostics if d.rule_id == "MCP108")
        assert mcp108.fix is not None
        pairs = {e.old: e.new for e in mcp108.fix.edits}
        assert pairs == {
            '"zod": "^3.0.0"': '"zod": "3.0.0"',
            '"@modelcontextprotocol/sdk": "^1.0.0"': '"@modelcontextprotocol/sdk": "1.0.0"',
        }

    def test_extras_and_markers_are_not_pinned(self, tmp_path):
        doc = self._pyproject_server(
            tmp_path, '["pkg[extra]>=1.2.3", "marker>=1.2.3 ; python_version>\'3\'"]'
        )
        mcp108 = next(d for d in doc.diagnostics if d.rule_id == "MCP108")
        # Both carry `[` or `;` → unsafe to rewrite textually → no fix proposed.
        assert mcp108.fix is None

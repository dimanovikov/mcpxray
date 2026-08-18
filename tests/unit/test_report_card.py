"""Unit tests for the verdict card formatter."""

from __future__ import annotations

from mcpxray.ir import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SOURCE_STATIC,
    Diagnostic,
    McpServer,
    ServerMeta,
    Tool,
)
from mcpxray.report import SUPPORTED_FORMATS, render
from mcpxray.report import card as card_fmt
from mcpxray.report.card import render_verdict
from mcpxray.score import score
from mcpxray.verdict import verdict


def _doc(*diags: Diagnostic, tools: int = 1, source_mode: str = SOURCE_STATIC) -> McpServer:
    s = McpServer(meta=ServerMeta(name="x", language="python"), source_mode=source_mode)
    s.diagnostics.extend(diags)
    for i in range(tools):
        s.tools.append(Tool(name=f"t{i}"))
    return s


class TestRegistration:
    def test_card_registered(self):
        assert "card" in SUPPORTED_FORMATS


class TestCardContent:
    def _out(self, doc, details=False):
        return render_verdict(verdict(doc), doc=doc, score_result=score(doc), details=details)

    def test_ok_card(self):
        out = self._out(_doc())
        assert "OK" in out
        assert "Looks clean" in out
        assert "100/100" in out

    def test_caution_card_lists_reason(self):
        out = self._out(_doc(Diagnostic("MCP104", SEVERITY_WARNING, "w")))
        assert "CAUTION" in out
        assert "Weak or empty input schemas" in out

    def test_danger_card(self):
        out = self._out(_doc(Diagnostic("MCP102", SEVERITY_ERROR, "e")))
        assert "DANGER" in out
        assert "Do not install" in out
        assert "Leaked secrets" in out

    def test_unknown_card_mentions_manifest(self):
        out = self._out(_doc(tools=0))
        assert "UNKNOWN" in out
        assert "--manifest" in out
        assert "couldn't find tool definitions" in out

    def test_details_appends_findings(self):
        out = self._out(_doc(Diagnostic("MCP103", SEVERITY_ERROR, "e")), details=True)
        assert "full findings" in out
        assert "MCP103" in out

    def test_details_hint_when_not_details(self):
        out = self._out(_doc(Diagnostic("MCP103", SEVERITY_ERROR, "e")), details=False)
        assert "--details" in out


class TestCardUnicodeFallback:
    def test_ascii_fallback(self, monkeypatch):
        monkeypatch.setattr(card_fmt, "_supports_unicode", lambda: False)
        out = render_verdict(
            verdict(_doc(Diagnostic("MCP102", SEVERITY_ERROR, "e"))),
            doc=_doc(Diagnostic("MCP102", SEVERITY_ERROR, "e")),
            score_result=score(_doc(Diagnostic("MCP102", SEVERITY_ERROR, "e"))),
        )
        assert "[DANGER]" in out
        assert "🔴" not in out

    def test_unicode_mode(self, monkeypatch):
        monkeypatch.setattr(card_fmt, "_supports_unicode", lambda: True)
        doc = _doc(Diagnostic("MCP102", SEVERITY_ERROR, "e"))
        out = render_verdict(verdict(doc), doc=doc, score_result=score(doc))
        assert "🔴 DANGER" in out


class TestCardViaRegistry:
    def test_render_card_dispatch(self):
        doc = _doc(Diagnostic("MCP102", SEVERITY_ERROR, "e"))
        out = render(doc.diagnostics, "card", doc=doc, score_result=score(doc))
        assert "DANGER" in out

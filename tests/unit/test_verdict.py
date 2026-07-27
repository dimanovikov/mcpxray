"""Unit tests for the verdict engine."""

from __future__ import annotations

from pathlib import Path

from mcpscore.extract import extractor_for
from mcpscore.ir import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SOURCE_MANIFEST,
    SOURCE_STATIC,
    Diagnostic,
    McpServer,
    ServerMeta,
    Tool,
)
from mcpscore.rules import run_all
from mcpscore.score import score
from mcpscore.verdict import TIER_CAUTION, TIER_DANGER, TIER_OK, TIER_UNKNOWN, verdict

FIXTURES = Path(__file__).parent.parent / "fixtures" / "servers"


def _server(*diags: Diagnostic, source_mode: str = SOURCE_STATIC, tools: int = 0) -> McpServer:
    s = McpServer(meta=ServerMeta(name="x"), source_mode=source_mode)
    s.diagnostics.extend(diags)
    for i in range(tools):
        s.tools.append(Tool(name=f"t{i}"))
    return s


class TestVerdictTiers:
    def test_clean_with_tools_is_ok(self):
        v = verdict(_server(tools=1))
        assert v.tier == TIER_OK
        assert v.headline == "Looks clean"
        assert v.reasons == []

    def test_no_tools_static_is_unknown(self):
        v = verdict(_server())
        assert v.tier == TIER_UNKNOWN
        assert "manifest" in v.recommendation.lower()

    def test_no_tools_manifest_is_ok(self):
        # The user handed us a manifest deliberately -> not "unknown".
        v = verdict(_server(source_mode=SOURCE_MANIFEST))
        assert v.tier == TIER_OK

    def test_error_is_danger(self):
        s = _server(Diagnostic("MCP102", SEVERITY_ERROR, "e"), tools=1)
        v = verdict(s)
        assert v.tier == TIER_DANGER
        assert v.headline == "Do not install this server"
        assert any(r.rule_id == "MCP102" for r in v.reasons)

    def test_warning_only_is_caution(self):
        s = _server(Diagnostic("MCP104", SEVERITY_WARNING, "w"), tools=1)
        v = verdict(s)
        assert v.tier == TIER_CAUTION
        assert any(r.rule_id == "MCP104" for r in v.reasons)


class TestVerdictReasons:
    def test_danger_reasons_scariest_first(self):
        s = _server(
            Diagnostic("MCP102", SEVERITY_ERROR, "e"),
            Diagnostic("MCP103", SEVERITY_ERROR, "e"),
            tools=1,
        )
        v = verdict(s)
        ids = [r.rule_id for r in v.reasons]
        assert ids[0] == "MCP103"  # RCE ranks above secrets
        assert ids[1] == "MCP102"

    def test_reasons_capped_at_five(self):
        diags = [Diagnostic(f"X{i}", SEVERITY_WARNING, "w") for i in range(7)]
        v = verdict(_server(*diags, tools=1))
        assert len(v.reasons) == 5

    def test_reason_counts(self):
        s = _server(
            Diagnostic("MCP103", SEVERITY_ERROR, "a"),
            Diagnostic("MCP103", SEVERITY_ERROR, "b"),
            Diagnostic("MCP102", SEVERITY_ERROR, "c"),
            tools=1,
        )
        v = verdict(s)
        assert {r.rule_id: r.count for r in v.reasons} == {"MCP103": 2, "MCP102": 1}

    def test_caution_recommendation_lists_top_reason(self):
        v = verdict(_server(Diagnostic("MCP104", SEVERITY_WARNING, "w"), tools=1))
        assert "weak or empty input schemas" in v.recommendation.lower()


class TestVerdictOnFixtures:
    def _check(self, rel: str) -> object:
        path = FIXTURES / rel
        doc = extractor_for(path).extract(path)
        run_all(doc)
        return verdict(doc, score(doc))

    def test_leaky_is_danger(self):
        assert self._check("leaky").tier == TIER_DANGER

    def test_poisoned_is_danger(self):
        assert self._check("poisoned").tier == TIER_DANGER

    def test_unpinned_is_caution(self):
        assert self._check("unpinned").tier == TIER_CAUTION

    def test_clean_is_ok(self):
        assert self._check("clean").tier == TIER_OK

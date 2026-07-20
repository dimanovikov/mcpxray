"""Unit tests for the IR."""

from __future__ import annotations

from mcpscore.ir import (
    ERROR_SCORE_CAP,
    RISK_WEIGHT,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Diagnostic,
    McpServer,
    ServerMeta,
    Tool,
    severity_rank,
)


def _server(*diags: Diagnostic) -> McpServer:
    s = McpServer(meta=ServerMeta(name="x"))
    s.diagnostics.extend(diags)
    return s


class TestSeverity:
    def test_rank_ordering(self):
        assert severity_rank(SEVERITY_ERROR) > severity_rank(SEVERITY_WARNING)
        assert severity_rank(SEVERITY_WARNING) > severity_rank(SEVERITY_INFO)
        assert severity_rank("bogus") == 0

    def test_risk_weight_monotonic(self):
        assert RISK_WEIGHT["critical"] > RISK_WEIGHT["high"]
        assert RISK_WEIGHT["high"] > RISK_WEIGHT["medium"]
        assert RISK_WEIGHT["medium"] > RISK_WEIGHT["low"]

    def test_error_score_cap_below_passing(self):
        assert ERROR_SCORE_CAP < 100


class TestDiagnostic:
    def test_defaults(self):
        d = Diagnostic("MCP101", SEVERITY_ERROR, "boom")
        assert d.tool is None and d.file is None and d.line is None
        assert d.severity == SEVERITY_ERROR


class TestMcpServer:
    def test_has_errors_and_errors_filter(self):
        s = _server(
            Diagnostic("MCP101", SEVERITY_ERROR, "e", tool="t1"),
            Diagnostic("MCP104", SEVERITY_WARNING, "w", tool="t2"),
            Diagnostic("MCP107", SEVERITY_INFO, "i"),
        )
        assert s.has_errors is True
        assert len(s.errors) == 1
        assert s.errors[0].tool == "t1"

    def test_no_errors(self):
        s = _server(Diagnostic("MCP104", SEVERITY_WARNING, "w"))
        assert s.has_errors is False
        assert s.errors == []


class TestTool:
    def test_tool_roundtrip(self):
        t = Tool(
            name="calc",
            description="Calculate things.",
            input_schema={"type": "object", "required": ["x"]},
            source_path="srv.py",
            line=12,
        )
        assert t.name == "calc"
        assert t.input_schema["required"] == ["x"]
        assert not t.runtime_only

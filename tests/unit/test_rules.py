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

    def test_mcp108_pip_pinning_predicate(self):
        from mcpscore.rules.builtin.supply import _is_pinned

        assert _is_pinned("==1.2.3")  # pip exact
        assert _is_pinned("~=1.2")  # pip compatible-release
        assert not _is_pinned(">=2")  # pip range
        assert not _is_pinned("flask")  # bare pip name (the unpinned fixture)

    def test_mcp108_npm_pinning_predicate(self):
        from mcpscore.rules.builtin.supply import _is_pinned

        assert _is_pinned("1.2.3")  # npm exact
        assert _is_pinned("v1.2.3")
        assert _is_pinned("=1.2.3")
        assert _is_pinned("1.2.3-beta.1")  # exact pre-release
        assert not _is_pinned("^1.2.3")  # caret range drifts
        assert not _is_pinned("~1.2.3")  # tilde range drifts
        assert not _is_pinned(">=1.2.3")
        assert not _is_pinned("1.x")
        assert not _is_pinned("*")
        assert not _is_pinned("latest")

    def test_mcp108_npm_deps_fire_without_lockfile(self, tmp_path):
        # A TS server whose package.json floats caret ranges and commits no lockfile.
        (tmp_path / "server.ts").write_text(
            'const s = { tool: () => {} };\ns.tool("ping", "p", {}, async () => ({}));\n',
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"zod": "^3.0.0", "@modelcontextprotocol/sdk": "^1.0.0"}}\n',
            encoding="utf-8",
        )
        ids, _ = _run(tmp_path)
        assert "MCP108" in ids  # ranges drift, no lockfile → flagged

    def test_mcp108_npm_lockfile_suppresses(self, tmp_path):
        # Same floating ranges, but a committed lockfile makes installs reproducible.
        (tmp_path / "server.ts").write_text(
            'const s = { tool: () => {} };\ns.tool("ping", "p", {}, async () => ({}));\n',
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"zod": "^3.0.0"}}\n', encoding="utf-8"
        )
        (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
        ids, _ = _run(tmp_path)
        assert "MCP108" not in ids

    def test_mcp104_weak_and_mcp106_incompat_schema(self):
        ids, _ = _run(FIXTURES / "weak_schema.json")
        assert "MCP104" in ids
        assert "MCP106" in ids

    def test_mcp105_schema_handler_drift(self):
        ids, _ = _run(FIXTURES / "typescript_drift")
        # exactly one drift finding — "mismatch" drifts, "consistent" does not
        assert ids.count("MCP105") == 1

    def test_findings_sorted_errors_first(self):
        ids, _ = _run(FIXTURES / "leaky")
        assert ids[0] in ("MCP102", "MCP103")  # both are ERROR severity

    def test_diagnostics_mirrored_to_doc(self):
        _, doc = _run(FIXTURES / "poisoned")
        assert doc.has_errors
        assert doc.errors  # property returns the error list


class TestMCP105Drift:
    """Schema/implementation drift — unit checks on the rule directly."""

    @staticmethod
    def _doc(schema: dict, handler_params):
        from mcpscore.ir import McpServer, ServerMeta, Tool

        return McpServer(
            meta=ServerMeta(language="typescript"),
            tools=[Tool(name="t", input_schema=schema, handler_params=handler_params)],
        )

    @staticmethod
    def _ids(doc):
        from mcpscore.rules.builtin.schema import SchemaImplDrift

        return [d.rule_id for d in SchemaImplDrift().check(doc)]

    def test_skipped_when_handler_params_none(self):
        # bare ``args`` / Python / manifest → undeterminable, can't compare.
        doc = self._doc({"type": "object", "properties": {"a": {"type": "string"}}}, None)
        assert self._ids(doc) == []

    def test_drift_both_directions(self):
        doc = self._doc(
            {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}},
            ["a", "c"],
        )
        assert self._ids(doc) == ["MCP105"]  # b ignored, c unvalidated

    def test_no_drift_when_consistent(self):
        doc = self._doc({"type": "object", "properties": {"x": {"type": "number"}}}, ["x"])
        assert self._ids(doc) == []

    def test_empty_handler_with_schema_is_drift(self):
        # handler takes () but the schema declares params → handler ignores them.
        doc = self._doc({"type": "object", "properties": {"a": {"type": "string"}}}, [])
        assert self._ids(doc) == ["MCP105"]


class TestMCP109Transport:
    """Insecure network transport — no TLS / no auth."""

    @staticmethod
    def _ids(src: str):
        from mcpscore.ir import McpServer, ServerMeta
        from mcpscore.rules.builtin.transport import InsecureTransport

        doc = McpServer(meta=ServerMeta(language="typescript"))
        doc.sources["server.ts"] = src
        return [d.rule_id for d in InsecureTransport().check(doc)]

    def test_stdio_not_flagged(self):
        src = "const t = new StdioServerTransport();\n"
        assert self._ids(src) == []

    def test_no_transport_not_flagged(self):
        assert self._ids("const x = 1;\n") == []

    def test_http_transport_no_tls_no_auth(self):
        src = 'const t = new StreamableHTTPServerTransport({ url: "http://example.com/mcp" });\n'
        ids = self._ids(src)
        assert ids.count("MCP109") == 2  # both: no TLS and no auth

    def test_https_suppresses_tls_finding(self):
        src = 'new StreamableHTTPServerTransport({ url: "https://example.com/mcp" });\n'
        assert self._ids(src) == ["MCP109"]  # only no-auth remains

    def test_auth_suppresses_auth_finding(self):
        src = (
            'new StreamableHTTPServerTransport({ url: "http://example.com" });\n'
            "async function authenticate(token) { return true; }\n"
        )
        assert self._ids(src) == ["MCP109"]  # only no-TLS remains

    def test_loopback_http_not_tls_flagged(self):
        # http on localhost isn't a TLS issue; only the missing-auth finding fires.
        src = 'new SSEServerTransport("/mcp"); const url = "http://localhost:3000";\n'
        assert self._ids(src) == ["MCP109"]

    def test_python_sse_transport_flagged(self):
        src = 'mcp.run(transport="sse")\n'
        assert self._ids(src) == ["MCP109"]

    def test_existing_fixtures_not_flagged(self):
        # stdio / FastMCP servers must not trip the transport rule.
        for fx in ("clean", "leaky", "poisoned", "bare", "typescript_clean"):
            ids, _ = _run(FIXTURES / fx)
            assert "MCP109" not in ids, f"{fx} unexpectedly flagged MCP109"

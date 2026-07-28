"""Unit tests for runtime ``tools/list`` capture (``runtime.py``)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mcpscore.extract.manifest import from_tools
from mcpscore.ir import SOURCE_RUNTIME
from mcpscore.rules import run_all
from mcpscore.runtime import (
    CaptureError,
    _initialize_msg,
    _initialized_notification,
    _tools_list_msg,
    capture_tools,
    split_command,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
SERVER = FIXTURES / "runtime_mcp_server.py"


def _argv() -> list[str]:
    # A real argv list — no string splitting, so it's robust on Windows paths.
    return [sys.executable, str(SERVER)]


class TestMessageBuilders:
    def test_initialize_request_carries_id_and_client(self):
        msg = _initialize_msg(7)
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == 7
        assert msg["method"] == "initialize"
        params = msg["params"]
        assert params["protocolVersion"]
        assert params["clientInfo"]["name"] == "mcpscore"
        assert params["capabilities"] == {}

    def test_initialized_notification_has_no_id(self):
        msg = _initialized_notification()
        assert msg["method"] == "notifications/initialized"
        assert "id" not in msg  # a notification expects no response

    def test_tools_list_request_carries_id(self):
        msg = _tools_list_msg(3)
        assert msg["id"] == 3
        assert msg["method"] == "tools/list"
        assert msg["params"] == {}


class TestSplitCommand:
    def test_splits_posix_argv(self):
        assert split_command("python -m myserver") == ["python", "-m", "myserver"]

    def test_quoted_path_kept_as_one_token(self):
        argv = split_command("'python with space' server.py")
        assert argv[0] == "python with space"
        assert argv[-1] == "server.py"

    def test_empty_raises(self):
        with pytest.raises(CaptureError):
            split_command("")

    def test_whitespace_only_raises(self):
        with pytest.raises(CaptureError):
            split_command("   ")


class TestCaptureToolsHappyPath:
    def test_captures_tools_and_server_info(self):
        result = capture_tools(_argv(), init_timeout=10.0, list_timeout=10.0)
        assert result.server_name == "test-runtime-server"
        assert result.server_version == "0.1.0"
        names = sorted(t["name"] for t in result.tools)
        assert names == ["add", "ping"]

    def test_add_schema_round_trips(self):
        result = capture_tools(_argv(), init_timeout=10.0, list_timeout=10.0)
        add = next(t for t in result.tools if t["name"] == "add")
        schema = add["inputSchema"]
        assert schema["required"] == ["a", "b"]
        assert set(schema["properties"]) == {"a", "b"}


class TestCaptureToolsFailures:
    def test_missing_executable(self):
        with pytest.raises(CaptureError, match="executable not found"):
            capture_tools(["definitely_not_a_real_exe_xyz_42"])

    def test_non_mcp_program_closes_output(self):
        # Prints non-JSON then exits → no initialize response → EOF.
        with pytest.raises(CaptureError, match="closed its output|initialize"):
            capture_tools([sys.executable, "-c", "print('not jsonrpc')"], init_timeout=5.0)

    def test_unresponsive_server_times_out(self):
        # Never answers initialize → timeout (and the process must be torn down).
        with pytest.raises(CaptureError, match="timed out|initialize"):
            capture_tools(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                init_timeout=0.5,
                list_timeout=0.5,
            )

    def test_empty_argv_raises(self):
        with pytest.raises(CaptureError, match="no launch command"):
            capture_tools([])


class TestFromToolsSeam:
    @staticmethod
    def _tools():
        return [
            {
                "name": "add",
                "description": "Add two numbers.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                    "required": ["a", "b"],
                },
            },
            {"name": "ping", "description": "Health check."},  # no inputSchema → {}
        ]

    def test_builds_runtime_server(self):
        doc = from_tools(self._tools(), name="srv", version="1.2.3", path_str="/x")
        assert doc.source_mode == SOURCE_RUNTIME
        assert doc.meta.name == "srv"
        assert doc.meta.version == "1.2.3"
        assert doc.meta.language is None
        assert [t.name for t in doc.tools] == ["add", "ping"]
        assert all(t.runtime_only for t in doc.tools)

    def test_schema_fallback_and_default(self):
        doc = from_tools(
            [
                {
                    "name": "x",
                    "input_schema": {
                        "type": "object",
                        "properties": {"a": {"type": "string"}},
                    },
                }
            ]
        )
        assert doc.tools[0].input_schema["properties"]["a"] == {"type": "string"}
        # missing inputSchema entirely → empty dict
        doc2 = from_tools([{"name": "y"}])
        assert doc2.tools[0].input_schema == {}

    def test_entry_without_name_is_skipped(self):
        doc = from_tools([{"description": "no name"}, {"name": "ok"}])
        assert [t.name for t in doc.tools] == ["ok"]

    def test_rules_still_run_on_runtime_tools(self):
        # A weak schema (properties but no required) must still fire MCP104,
        # proving the captured tools flow through the rule engine.
        doc = from_tools(
            [
                {
                    "name": "weak",
                    "description": "d",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"a": {"type": "string"}},
                    },
                }
            ]
        )
        run_all(doc)
        assert "MCP104" in [d.rule_id for d in doc.diagnostics]

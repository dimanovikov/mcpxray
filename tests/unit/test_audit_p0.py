"""Regressions for the three P0 findings from the 2026-09 security audit.

Each of these was reproducible against real, published MCP servers, and each
made the scanner report a clean result on input it had not actually analysed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mcpxray.extract.python_static import PythonExtractor
from mcpxray.ir import McpServer, ServerMeta
from mcpxray.rules.builtin.source import SecretExposure


def _write(tmp_path: Path, name: str, body: str) -> Path:
    (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


class TestLowLevelPythonServer:
    """P0-1: the official Python servers declare tools through the low-level
    ``@server.list_tools()`` decorator, which the extractor did not recognise,
    so `fetch`, `git` and `time` all scanned as an empty, flawless server."""

    def test_tools_are_extracted_from_list_tools_decorator(self, tmp_path: Path):
        root = _write(
            tmp_path,
            "server.py",
            """
            from mcp.server import Server
            from mcp.types import Tool

            server = Server("demo")

            @server.list_tools()
            async def list_tools() -> list[Tool]:
                return [
                    Tool(
                        name="fetch",
                        description="Fetch a URL and return its contents.",
                        inputSchema={"type": "object", "properties": {"url": {"type": "string"}}},
                    )
                ]
            """,
        )
        doc = PythonExtractor().extract(root)
        assert [t.name for t in doc.tools] == ["fetch"]
        assert doc.tools[0].description.startswith("Fetch a URL")
        assert doc.tools[0].input_schema["properties"]["url"]["type"] == "string"


class TestNothingExtracted:
    """P0-2: a tree the extractor could not read scored 100/A with no findings.
    Reporting a grade for input that was never analysed is the failure mode that
    matters most for a security tool, so absence of any surface must be visible."""

    def test_empty_server_is_flagged_as_unanalysed(self):
        doc = McpServer(meta=ServerMeta(name="demo", language="python"))
        assert doc.is_unanalysed is True

    def test_a_server_with_only_resources_is_still_analysed(self):
        from mcpxray.ir import Resource

        doc = McpServer(
            meta=ServerMeta(name="demo", language="python"),
            resources=[Resource(uri="file:///x")],
        )
        assert doc.is_unanalysed is False


class TestGoogleApiKey:
    """P0-3: the pattern spelled the prefix in lower case and compiled without
    re.IGNORECASE, so a Google API key in source was never reported."""

    def test_google_api_key_in_source_is_reported(self):
        doc = McpServer(
            meta=ServerMeta(name="demo", language="python"),
            sources={"server.py": 'KEY = "AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY"\n'},
        )
        found = list(SecretExposure().check(doc))
        assert found, "a well-formed Google API key must be reported"
        assert "google" in found[0].message.lower()


class TestNonLiteralToolMetadata:
    """The official `git` and `time` servers name their tools through an enum
    and build schemas by calling a model, so requiring literals dropped every
    tool they declare. A dropped tool is an unreported tool."""

    def test_enum_member_names_are_resolved(self, tmp_path: Path):
        root = _write(
            tmp_path,
            "server.py",
            """
            from enum import Enum
            from mcp.server import Server
            from mcp.types import Tool

            class GitTools(str, Enum):
                STATUS = "git_status"
                DIFF = "git_diff"

            server = Server("git")

            @server.list_tools()
            async def list_tools() -> list[Tool]:
                return [
                    Tool(name=GitTools.STATUS, description="Show status", inputSchema={}),
                    Tool(name=GitTools.DIFF.value, description="Show diff", inputSchema={}),
                ]
            """,
        )
        doc = PythonExtractor().extract(root)
        assert sorted(t.name for t in doc.tools) == ["git_diff", "git_status"]

    def test_a_schema_we_could_not_read_is_not_called_weak(self, tmp_path: Path):
        """inputSchema=Model.model_json_schema() is a real schema we cannot see
        statically. Reporting it as missing would be a false positive on a
        correctly written server."""
        root = _write(
            tmp_path,
            "server.py",
            """
            from mcp.server import Server
            from mcp.types import Tool

            server = Server("git")

            @server.list_tools()
            async def list_tools() -> list[Tool]:
                return [
                    Tool(
                        name="git_status",
                        description="Show the working tree status",
                        inputSchema=GitStatus.model_json_schema(),
                    )
                ]
            """,
        )
        doc = PythonExtractor().extract(root)
        assert [t.name for t in doc.tools] == ["git_status"]
        assert doc.tools[0].schema_unresolved is True


class TestDangerousPrimitivesInJavaScript:
    """P1-4: MCP103 listed only Python primitives, so a TypeScript server
    shelling out through child_process scanned clean. TypeScript is the
    dominant language for MCP servers, which made the rule near-useless where
    it mattered most."""

    def _findings(self, source: str) -> list:
        from mcpxray.ir import McpServer, ServerMeta
        from mcpxray.rules.builtin.source import DangerousCapabilities

        doc = McpServer(
            meta=ServerMeta(name="demo", language="typescript"),
            sources={"index.ts": source},
        )
        return list(DangerousCapabilities().check(doc))

    def test_exec_sync_is_reported(self):
        found = self._findings(
            'import { execSync } from "child_process";\n'
            "export const run = (cmd: string) => execSync(cmd).toString();\n"
        )
        assert found, "execSync is arbitrary shell execution"

    def test_new_function_is_reported(self):
        found = self._findings('const f = new Function("a", "return a * 2");\n')
        assert found, "new Function is arbitrary code execution"

    def test_regex_exec_is_not_reported(self):
        """`/re/.exec(s)` is ordinary JavaScript. Flagging it would bury the
        real findings under noise, which is how linters get switched off."""
        found = self._findings("const m = /a(b)c/.exec(input);\nconst n = re.exec(s);\n")
        assert not found, f"regex .exec must not be a finding: {[f.message for f in found]}"


class TestTestTreesAreNotScanned:
    """Skipping test trees was written for Python names only, so JavaScript's
    `__tests__` slipped through. Harmless until MCP103 learned JS primitives,
    at which point the official `filesystem` server dropped from A to F on two
    findings that were both in its own test suite."""

    def _scan(self, tmp_path: Path, rel: str, body: str):
        from mcpxray.extract.python_static import _iter_source_files

        # pytest names its tmp dirs after the test function, so they start with
        # "test_" — which reads as "the caller scoped into a test tree" and
        # disables the very filter under test. Walk from a neutral root.
        root = tmp_path / "project"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return [p.name for p in _iter_source_files(root, (".ts", ".js"))]

    def test_js_test_directory_is_skipped(self, tmp_path: Path):
        files = self._scan(tmp_path, "__tests__/thing.test.ts", "execSync('ls');\n")
        assert files == []

    def test_colocated_test_file_is_skipped(self, tmp_path: Path):
        files = self._scan(tmp_path, "src/thing.spec.ts", "execSync('ls');\n")
        assert files == []

    def test_real_source_is_still_scanned(self, tmp_path: Path):
        files = self._scan(tmp_path, "src/index.ts", "execSync('ls');\n")
        assert files == ["index.ts"]


class TestUnanalysedCarriesNoNumber:
    """A score of 94 next to a null grade still reads as a verdict."""

    def test_score_is_withheld_too(self, tmp_path: Path):
        import json

        from typer.testing import CliRunner

        from mcpxray.cli import app

        (tmp_path / "server.py").write_text("VALUE = 1\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0"\n', encoding="utf-8"
        )
        r = CliRunner().invoke(app, ["scan", str(tmp_path), "--format", "json"])
        summary = json.loads(r.stdout)["summary"]
        assert summary["analysed"] is False
        assert summary["grade"] is None
        assert summary["score"] is None


class TestEverySecretPatternMatchesARealShape:
    """P2-6: the Google pattern spelled its prefix in the wrong case and matched
    nothing, and nothing in the suite noticed. Each pattern now has a sample of
    the shape it claims to detect, so the next such typo fails a test."""

    # Assembled from parts on purpose. A literal of the right shape is a real
    # secret as far as any scanner is concerned, and GitHub push protection
    # rejected this file when the samples were spelled out — which is the
    # behaviour we are testing for, arriving from the other direction.
    _G = "glpat" + "-"
    _H = "ghp" + "_"
    _S = "xoxb" + "-"
    _A = "AKIA" + "IOSFODNN7"
    _O = "sk" + "-"
    _K = "AIza" + "SyD"

    SAMPLES = {
        "private key": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1r\n",
        "OpenAI-style API key": f'KEY = "{_O}proj1234567890abcdefghij1234567890"',
        "AWS access key id": f'AWS = "{_A}EXAMPLE"',
        "GitHub token": f'GH = "{_H}16C7e42F292c6912E7710c838347Ae178B4a1234"',
        "GitLab token": f'GL = "{_G}ABCDEfghij1234567890"',
        "Slack token": f'SL = "{_S}1234567890-abcdefghij"',
        "Google API key": f'GK = "{_K}-9tSrke72PouQMnMX-a7eZSW0jkFMBWY"',
        "hardcoded credential": 'password = "s3cret-value-here-1234"',
    }

    @pytest.mark.parametrize("label", sorted(SAMPLES))
    def test_pattern_fires(self, label: str):
        from mcpxray.ir import McpServer, ServerMeta
        from mcpxray.rules.builtin.source import SecretExposure

        doc = McpServer(
            meta=ServerMeta(name="demo", language="python"),
            sources={"server.py": self.SAMPLES[label]},
        )
        messages = [d.message for d in SecretExposure().check(doc)]
        assert any(label in m for m in messages), (
            f"{label!r} did not match its own sample shape; got {messages}"
        )

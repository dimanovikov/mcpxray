"""Unit tests for the Python static extractor, manifest extractor, and registry."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from mcpxray.extract import extractor_for, extractors
from mcpxray.extract.python_static import (
    PythonExtractor,
    _annotation_to_schema,
    _extract_function,
    _iter_python_files,
)
from mcpxray.extract.typescript_static import (
    TypescriptExtractor,
    _iter_typescript_files,
    _zod_to_schema,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "servers"


# --- type-hint → schema ------------------------------------------------------


class TestAnnotationMapping:
    def _ann(self, expr: str) -> ast.AST:
        return ast.parse(expr, mode="eval").body

    def test_primitives(self):
        assert _annotation_to_schema(self._ann("int")) == {"type": "integer"}
        assert _annotation_to_schema(self._ann("str")) == {"type": "string"}
        assert _annotation_to_schema(self._ann("bool")) == {"type": "boolean"}
        assert _annotation_to_schema(self._ann("float")) == {"type": "number"}

    def test_list_and_dict(self):
        assert _annotation_to_schema(self._ann("list[str]")) == {
            "type": "array",
            "items": {"type": "string"},
        }
        assert _annotation_to_schema(self._ann("dict[str, int]")) == {"type": "object"}

    def test_optional_and_union(self):
        assert _annotation_to_schema(self._ann("Optional[int]")) == {"type": "integer"}
        assert _annotation_to_schema(self._ann("int | None")) == {"type": "integer"}

    def test_custom_type_is_any(self):
        # custom class / unknown → empty schema (we can't resolve it statically)
        assert _annotation_to_schema(self._ann("SomeModel")) == {}


# --- Python static extractor -------------------------------------------------


class TestPythonExtractor:
    def setup_method(self):
        self.server = PythonExtractor().extract(FIXTURES / "clean")

    def test_finds_both_tools(self):
        names = sorted(t.name for t in self.server.tools)
        assert names == ["add", "greet"]

    def test_docstring_becomes_description(self):
        add = next(t for t in self.server.tools if t.name == "add")
        assert add.description == "Add two integers and return their sum."

    def test_decorator_overrides_name_and_description(self):
        greet = next(t for t in self.server.tools if t.name == "greet")
        assert greet.description == "Greet a person by name."
        assert greet.name == "greet"  # overridden from _greet

    def test_schema_required_vs_optional(self):
        add = next(t for t in self.server.tools if t.name == "add")
        greet = next(t for t in self.server.tools if t.name == "greet")
        assert add.input_schema["required"] == ["a", "b"]
        assert add.input_schema["properties"]["a"] == {"type": "integer"}
        assert greet.input_schema["required"] == ["name"]  # greeting has a default
        assert "greeting" in greet.input_schema["properties"]

    def test_provenance(self):
        for t in self.server.tools:
            assert t.source_path.endswith("server.py")
            assert t.line is not None and t.line > 0
            assert not t.runtime_only


# --- MCP context parameter is not user input ---------------------------------


class TestContextParam:
    """FastMCP injects a `Context` param; it must stay out of the input schema."""

    @staticmethod
    def _tool(src: str):
        tree = ast.parse(textwrap.dedent(src))
        fn = next(
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        return _extract_function(fn, "x.py")

    def test_ctx_by_name_excluded(self):
        tool = self._tool(
            """
            @mcp.tool()
            def f(ctx, a: int, b: int = 0):
                \"\"\"doc\"\"\"
                return a + b
            """
        )
        props = tool.input_schema["properties"]
        assert "ctx" not in props
        assert set(props) == {"a", "b"}
        assert tool.input_schema["required"] == ["a"]  # b has a default

    def test_typed_context_excluded(self):
        tool = self._tool(
            """
            @mcp.tool()
            def g(ctx: Context, x: str) -> str:
                \"\"\"doc\"\"\"
                return x
            """
        )
        assert "ctx" not in tool.input_schema["properties"]
        assert tool.input_schema["required"] == ["x"]

    def test_qualified_context_type_excluded(self):
        tool = self._tool(
            """
            @mcp.tool()
            def h(request: mcp.Context, x: str) -> str:
                \"\"\"doc\"\"\"
                return x
            """
        )
        assert "request" not in tool.input_schema["properties"]

    def test_applies_to(self):
        ext = PythonExtractor()
        assert ext.applies_to(FIXTURES / "clean")
        assert ext.applies_to(FIXTURES / "clean" / "server.py")
        assert not ext.applies_to(FIXTURES / "clean_manifest.json")


# --- test/fixture trees are never walked -------------------------------------


class TestSkipDirs:
    @staticmethod
    def _touch(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")

    def test_iter_skips_test_and_fixture_dirs(self, tmp_path):
        self._touch(tmp_path / "src" / "app.py")
        self._touch(tmp_path / "tests" / "test_app.py")
        self._touch(tmp_path / "test" / "t.py")
        self._touch(tmp_path / "fixtures" / "data.py")
        self._touch(tmp_path / "test_foo" / "m.py")  # test_* prefix
        self._touch(tmp_path / "foo_test" / "m.py")  # _test suffix
        files = [p.name for p in _iter_python_files(tmp_path)]
        assert files == ["app.py"]

    def test_explicit_scope_into_test_dir_still_scans_it(self, tmp_path):
        # "tests" is pruned only as a *child* during a walk; pointed at directly,
        # it is scanned (lets --scope tests still surface what's there).
        self._touch(tmp_path / "tests" / "test_app.py")
        files = [p.name for p in _iter_python_files(tmp_path / "tests")]
        assert files == ["test_app.py"]


# --- TypeScript static extractor ---------------------------------------------


class TestTypescriptExtractor:
    def setup_method(self):
        self.server = TypescriptExtractor().extract(FIXTURES / "typescript_clean")

    def test_language(self):
        assert self.server.meta.language == "typescript"

    def test_finds_highlevel_tools(self):
        assert sorted(t.name for t in self.server.tools) == ["add", "greet", "tags"]

    def test_registertool_description_and_schema(self):
        greet = next(t for t in self.server.tools if t.name == "greet")
        assert greet.description == "Greet a user by name."
        assert greet.input_schema["properties"] == {"name": {"type": "string"}}
        assert greet.input_schema["required"] == ["name"]

    def test_tool_shorthand_schema(self):
        add = next(t for t in self.server.tools if t.name == "add")
        assert add.description == "Add two numbers."
        assert add.input_schema["properties"]["a"] == {"type": "number"}
        assert sorted(add.input_schema["required"]) == ["a", "b"]

    def test_zod_array_param(self):
        tags = next(t for t in self.server.tools if t.name == "tags")
        assert tags.input_schema["properties"]["items"] == {"type": "array"}

    def test_provenance(self):
        for t in self.server.tools:
            assert t.source_path.endswith("server.ts")
            assert t.line and t.line > 0
            assert not t.runtime_only

    def test_sources_populated_for_secret_scanning(self):
        # Populating .sources is what lets MCP102/103 scan .ts text for free.
        assert any(p.endswith("server.ts") for p in self.server.sources)

    def test_lowlevel_tools_parsed(self):
        server = TypescriptExtractor().extract(FIXTURES / "typescript_lowlevel")
        assert [t.name for t in server.tools] == ["ping"]
        ping = server.tools[0]
        assert ping.description == "Health-check ping."
        assert ping.input_schema["properties"]["host"] == {"type": "string"}
        assert ping.input_schema["required"] == ["host"]

    def test_applies_to(self):
        ext = TypescriptExtractor()
        assert ext.applies_to(FIXTURES / "typescript_clean")
        assert ext.applies_to(FIXTURES / "typescript_clean" / "server.ts")
        assert not ext.applies_to(FIXTURES / "clean_manifest.json")

    def test_python_wins_mixed_repo(self, tmp_path):
        # .py present → PythonExtractor applies; TS must not shadow it.
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.ts").write_text('server.tool("x", "y", {}, () => ({}));\n', encoding="utf-8")
        assert extractor_for(tmp_path).__class__.__name__ == "PythonExtractor"

    def test_ts_wins_pure_ts_repo(self, tmp_path):
        (tmp_path / "s.ts").write_text('server.tool("x", "y", {}, () => ({}));\n', encoding="utf-8")
        assert extractor_for(tmp_path).__class__.__name__ == "TypescriptExtractor"

    def test_iter_skips_declaration_files(self, tmp_path):
        (tmp_path / "real.ts").write_text("export const x = 1;\n", encoding="utf-8")
        (tmp_path / "types.d.ts").write_text("export declare const y: number;\n", encoding="utf-8")
        assert [p.name for p in _iter_typescript_files(tmp_path)] == ["real.ts"]

    def test_zod_to_schema_mapping(self):
        schema = _zod_to_schema("a: z.string(), b: z.number(), c: z.integer(), d: z.boolean()")
        assert schema == {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "number"},
                "c": {"type": "integer"},
                "d": {"type": "boolean"},
            },
            "required": ["a", "b", "c", "d"],
        }

    def test_zod_unknown_type_skipped_not_emptied(self):
        # z.custom() is unmappable → the prop is dropped, NOT emitted as {} (an
        # empty {} prop would falsely trip MCP104 "parameter has no type").
        schema = _zod_to_schema("a: z.string(), b: z.custom()")
        assert schema["properties"] == {"a": {"type": "string"}}
        assert schema["required"] == ["a"]


# --- manifest extractor ------------------------------------------------------
class TestManifestExtractor:
    def test_extracts_runtime_tools(self):
        ext = extractor_for(FIXTURES / "clean_manifest.json")
        assert ext is not None
        server = ext.extract(FIXTURES / "clean_manifest.json")
        assert len(server.tools) == 1
        tool = server.tools[0]
        assert tool.name == "list_files"
        assert tool.description == "List files in a directory."
        assert tool.input_schema["required"] == ["path"]
        assert tool.runtime_only is True

    def test_wrapped_jsonrpc_response(self):
        from mcpxray.extract.manifest import _find_tools

        wrapped = {"result": {"tools": [{"name": "x"}]}}
        assert _find_tools(wrapped) == [{"name": "x"}]


# --- registry ----------------------------------------------------------------


class TestRegistry:
    def test_builtin_extractors_registered(self):
        ids = {type(e).__name__ for e in (cls() for cls in extractors())}
        assert {"PythonExtractor", "TypescriptExtractor", "ManifestExtractor"} <= ids

    def test_python_registered_before_typescript(self):
        # Registration order decides mixed-repo resolution: Python must win a tree
        # that has both .py and .ts source.
        names = [cls.__name__ for cls in extractors()]
        assert names.index("PythonExtractor") < names.index("TypescriptExtractor")

    def test_extractor_for_dir(self):
        assert extractor_for(FIXTURES / "clean").__class__.__name__ == "PythonExtractor"

    def test_extractor_for_unknown(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "readme.txt").write_text("hi", encoding="utf-8")
        assert extractor_for(empty) is None  # no .py, no manifest

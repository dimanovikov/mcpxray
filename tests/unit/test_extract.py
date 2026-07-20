"""Unit tests for the Python static extractor, manifest extractor, and registry."""

from __future__ import annotations

import ast
from pathlib import Path

from mcpscore.extract import extractor_for, extractors
from mcpscore.extract.python_static import (
    PythonExtractor,
    _annotation_to_schema,
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

    def test_applies_to(self):
        ext = PythonExtractor()
        assert ext.applies_to(FIXTURES / "clean")
        assert ext.applies_to(FIXTURES / "clean" / "server.py")
        assert not ext.applies_to(FIXTURES / "clean_manifest.json")


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
        from mcpscore.extract.manifest import _find_tools

        wrapped = {"result": {"tools": [{"name": "x"}]}}
        assert _find_tools(wrapped) == [{"name": "x"}]


# --- registry ----------------------------------------------------------------


class TestRegistry:
    def test_builtin_extractors_registered(self):
        ids = {type(e).__name__ for e in (cls() for cls in extractors())}
        assert {"PythonExtractor", "ManifestExtractor"} <= ids

    def test_extractor_for_dir(self):
        assert extractor_for(FIXTURES / "clean").__class__.__name__ == "PythonExtractor"

    def test_extractor_for_unknown(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "readme.txt").write_text("hi", encoding="utf-8")
        assert extractor_for(empty) is None  # no .py, no manifest

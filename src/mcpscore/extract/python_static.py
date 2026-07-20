"""Static Python extractor.

Parses MCP server source with :mod:`ast` (no import, no execution) and builds a
:class:`~mcpscore.ir.McpServer`. Recognises the FastMCP / ``server.tool()``
decorator family::

    mcp = FastMCP("...")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        \"\"\"Add two integers.\"\"\"
        ...

The tool's description comes from the decorator's ``description=`` kwarg or the
function docstring; the input schema is derived from parameter type hints.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from mcpscore.extract.base import Extractor, register_extractor
from mcpscore.ir import SOURCE_STATIC, McpServer, ServerMeta, Tool

# Directories never to descend into when walking a source tree.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
}

_PRIMITIVES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
_CONTAINER_SEQ = {"list", "List", "set", "Set", "frozenset", "tuple", "Tuple", "Sequence"}
_CONTAINER_MAP = {"dict", "Dict", "Mapping", "OrderedDict"}
_OPTIONAL = {"Optional"}
_UNION = {"Union"}


# --- type-hint (AST) → JSON Schema fragment ---------------------------------


def _is_none(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (
        isinstance(node, ast.Name) and node.id == "NoneType"
    )


def _flatten_bitor(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_bitor(node.left) + _flatten_bitor(node.right)
    return [node]


def _subscript_container(node: ast.Subscript) -> str:
    value = node.value
    return value.id if isinstance(value, ast.Name) else ""


def _slice_items(node: ast.AST) -> tuple[ast.AST, ...]:
    slice_node = node
    if isinstance(slice_node, ast.Tuple):
        return slice_node.elts
    return (slice_node,)


def _annotation_to_schema(node: ast.AST | None) -> dict:
    """Best-effort mapping of an AST annotation to a JSON Schema fragment."""
    if node is None:
        return {}
    if isinstance(node, ast.Name):
        if node.id in _PRIMITIVES:
            return {"type": _PRIMITIVES[node.id]}
        return {}  # Any / custom class — we can't resolve it statically
    if isinstance(node, ast.Constant):
        return {}
    if isinstance(node, ast.Subscript):
        container = _subscript_container(node)
        items = _slice_items(node.slice)
        if container in _CONTAINER_SEQ:
            inner = items[0] if items else None
            return {"type": "array", "items": _annotation_to_schema(inner)}
        if container in _CONTAINER_MAP:
            return {"type": "object"}
        if container in _OPTIONAL:
            return _annotation_to_schema(items[0] if items else None)
        if container in _UNION:
            non_none = [t for t in items if not _is_none(t)]
            return _annotation_to_schema(non_none[0]) if len(non_none) == 1 else {}
        return {}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):  # PEP 604 X | Y
        non_none = [p for p in _flatten_bitor(node) if not _is_none(p)]
        return _annotation_to_schema(non_none[0]) if len(non_none) == 1 else {}
    return {}  # ast.Attribute (qualified type) etc.


# --- decorator detection + tool metadata ------------------------------------


def _decorator_is_tool(node: ast.AST) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return (isinstance(target, ast.Attribute) and target.attr == "tool") or (
        isinstance(target, ast.Name) and target.id == "tool"
    )


def _decorator_meta(node: ast.AST) -> tuple[str | None, str | None]:
    """Extract ``name=`` / ``description=`` kwargs from a tool decorator call."""
    name = desc = None
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                name = kw.value.value if isinstance(kw.value.value, str) else None
            elif kw.arg == "description" and isinstance(kw.value, ast.Constant):
                desc = kw.value.value if isinstance(kw.value.value, str) else None
    return name, desc


def _build_input_schema(func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    props: dict[str, dict] = {}
    required: list[str] = []
    args = func.args

    posargs = list(args.posonlyargs) + list(args.args)
    defaults = args.defaults  # align to the right across posonly + posorkw
    ndef = len(defaults)
    npos = len(posargs)
    for i, a in enumerate(posargs):
        if a.arg in ("self", "cls"):
            continue
        props[a.arg] = _annotation_to_schema(a.annotation)
        if i < npos - ndef:
            required.append(a.arg)

    for i, a in enumerate(args.kwonlyargs):
        props[a.arg] = _annotation_to_schema(a.annotation)
        if args.kw_defaults[i] is None:
            required.append(a.arg)

    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _extract_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    source_path: str,
) -> Tool | None:
    tool_deco = next((d for d in func.decorator_list if _decorator_is_tool(d)), None)
    if tool_deco is None:
        return None
    deco_name, deco_desc = _decorator_meta(tool_deco)
    docstring = ast.get_docstring(func, clean=True)
    return Tool(
        name=deco_name or func.name,
        description=deco_desc or docstring,
        input_schema=_build_input_schema(func),
        source_path=source_path,
        line=func.lineno,
    )


def _extract_file(path: Path, server: McpServer) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return  # unparseable file — leave to rules/CI to surface separately
    posix = path.as_posix()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tool = _extract_function(node, posix)
            if tool is not None:
                server.tools.append(tool)


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                files.append(Path(dirpath) / name)
    return sorted(files)


@register_extractor
class PythonExtractor(Extractor):
    """Extract tools from Python MCP server source (FastMCP ``@mcp.tool()``)."""

    language = "python"

    def applies_to(self, path: Path) -> bool:
        if path.is_file():
            return path.suffix == ".py"
        if path.is_dir():
            return any(f.suffix == ".py" for f in _iter_python_files(path))
        return False

    def extract(self, path: Path) -> McpServer:
        files = [path] if path.is_file() else _iter_python_files(path)
        server = McpServer(
            meta=ServerMeta(
                name=path.stem if path.is_file() else path.name,
                language=self.language,
                path=str(path),
            ),
            source_mode=SOURCE_STATIC,
        )
        for f in files:
            _extract_file(f, server)
        return server

"""Static Python extractor.

Parses MCP server source with :mod:`ast` (no import, no execution) and builds a
:class:`~mcpxray.ir.McpServer`. Recognises the FastMCP / ``server.tool()``
decorator family and the low-level ``@server.list_tools()`` handler::

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
import re
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from mcpxray.extract.base import Extractor, register_extractor
from mcpxray.ir import SOURCE_STATIC, McpServer, ServerMeta, Tool

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
    # Test/fixture trees are never application source and routinely hold fake
    # keys + example tool registrations that would pollute a real scan (e.g. the
    # modelcontextprotocol/python-sdk demo inflated to 420 tools / 34 secrets).
    "tests",
    "test",
    "testing",
    "fixtures",
    "fixture",
    "test_data",
    "testdata",
    "testdata_dir",
    # JavaScript/TypeScript conventions — the Python names above do not cover
    # them, which let `__tests__` through and turned a server's own test suite
    # into findings against the server.
    "__tests__",
    "__mocks__",
    "spec",
    "e2e",
    "coverage",
}


def _is_test_dir(name: str) -> bool:
    """``test_foo`` / ``foo_test`` style dirs (a set can't express prefixes)."""
    return name.startswith("test_") or name.endswith("_test")


def _is_test_file(name: str) -> bool:
    """``thing.test.ts`` / ``thing.spec.js`` — JS keeps tests beside the source."""
    stem = name.rsplit(".", 1)[0]
    return stem.endswith((".test", ".spec")) or stem.startswith("test_")


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


def _looks_like_context(arg_name: str, annotation: ast.AST | None) -> bool:
    """True if this parameter is the MCP request context (framework-injected, not user input).

    FastMCP injects a ``Context`` object into every tool; by convention it is named
    ``ctx`` and/or typed ``Context`` (or ``mcp.Context``). Like the SDK, we exclude
    it from the input schema so it isn't mistaken for a user-supplied argument.
    """
    if arg_name == "ctx":
        return True
    if isinstance(annotation, ast.Name):
        return annotation.id == "Context"
    return isinstance(annotation, ast.Attribute) and annotation.attr == "Context"


def _build_input_schema(func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    props: dict[str, dict] = {}
    required: list[str] = []
    args = func.args

    posargs = list(args.posonlyargs) + list(args.args)
    defaults = args.defaults  # align to the right across posonly + posorkw
    ndef = len(defaults)
    npos = len(posargs)
    for i, a in enumerate(posargs):
        if a.arg in ("self", "cls") or _looks_like_context(a.arg, a.annotation):
            continue
        props[a.arg] = _annotation_to_schema(a.annotation)
        if i < npos - ndef:
            required.append(a.arg)

    for i, a in enumerate(args.kwonlyargs):
        if _looks_like_context(a.arg, a.annotation):
            continue
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


# --- low-level server: @server.list_tools() returning [Tool(...)] ------------


def _decorator_is_list_tools(node: ast.AST) -> bool:
    """``@server.list_tools()`` — the low-level SDK's tool declaration hook."""
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr == "list_tools"


def _literal(node: ast.AST | None):
    """Best-effort literal value, or ``None`` when the expression is computed."""
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _enum_values(tree: ast.Module) -> dict[str, str]:
    """Map ``ClassName.MEMBER`` to its string value for enums defined in this file.

    The official ``git`` and ``time`` servers name tools through an enum rather
    than a literal, so without this every tool they declare is dropped.
    """
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            target = stmt.targets[0]
            if (
                isinstance(target, ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                values[f"{node.name}.{target.id}"] = stmt.value.value
    return values


def _dotted(node: ast.AST) -> str | None:
    """``GitTools.STATUS`` -> that text; anything more complex -> None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _resolve_name(node: ast.AST | None, enums: dict[str, str]) -> str | None:
    """A tool name from a literal, or from an enum member (with or without ``.value``)."""
    literal = _literal(node)
    if isinstance(literal, str) and literal:
        return literal
    # ``GitTools.STATUS.value`` — unwrap the ``.value`` access first.
    if isinstance(node, ast.Attribute) and node.attr == "value":
        node = node.value
    dotted = _dotted(node) if node is not None else None
    return enums.get(dotted) if dotted else None


def _tool_from_call(node: ast.Call, source_path: str, enums: dict[str, str]) -> Tool | None:
    """Build a Tool from a ``Tool(name=..., description=..., inputSchema=...)`` call."""
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if called != "Tool":
        return None

    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    name = _resolve_name(kwargs.get("name"), enums)
    if not name:
        return None  # a tool we cannot name is a tool we cannot report on

    schema_node = kwargs.get("inputSchema")
    schema = _literal(schema_node)
    return Tool(
        name=name,
        description=_literal(kwargs.get("description")),
        input_schema=schema if isinstance(schema, dict) else {},
        schema_unresolved=schema_node is not None and not isinstance(schema, dict),
        source_path=source_path,
        line=node.lineno,
        # The low-level SDK dispatches every tool through one call_tool handler,
        # so there are no per-tool parameters to compare the schema against.
        # Leaving this None keeps MCP105 (schema/handler drift) from firing on
        # an absence it cannot interpret.
        handler_params=None,
    )


def _extract_list_tools(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    source_path: str,
    enums: dict[str, str],
) -> list[Tool]:
    """Tools declared in the body of a ``@server.list_tools()`` handler.

    The official Python servers (fetch, git, time) all use this shape rather
    than FastMCP's ``@mcp.tool()``. Missing it meant they extracted as empty
    servers and scored a flawless grade.
    """
    if not any(_decorator_is_list_tools(d) for d in func.decorator_list):
        return []
    tools: list[Tool] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.List):
            continue
        for element in node.value.elts:
            if isinstance(element, ast.Call):
                tool = _tool_from_call(element, source_path, enums)
                if tool is not None:
                    tools.append(tool)
    return tools


def _extract_file(path: Path, server: McpServer) -> None:
    text = path.read_text(encoding="utf-8")
    posix = path.as_posix()
    server.sources[posix] = text
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return  # unparseable file — leave to rules/CI to surface separately
    enums = _enum_values(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tool = _extract_function(node, posix)
            if tool is not None:
                server.tools.append(tool)
            server.tools.extend(_extract_list_tools(node, posix, enums))


# --- project metadata (dependencies, lockfiles) for supply-chain rules -------

_DEP_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(.*)$")
_LOCKFILES = {"uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "requirements.txt"}


def _split_dep(dep: str) -> tuple[str, str]:
    m = _DEP_RE.match(dep)
    if not m:
        return "", ""
    return m.group(1), m.group(2).strip()


def _load_pyproject(root: Path, server: McpServer) -> None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return
    for dep in (data.get("project") or {}).get("dependencies") or []:
        name, spec = _split_dep(str(dep))
        if name:
            server.dependencies[name] = spec
    if server.dependencies:
        server.dep_file = str(pyproject)  # provenance for `--fix`


def _find_lockfiles(root: Path, server: McpServer) -> None:
    for name in _LOCKFILES:
        if (root / name).is_file():
            server.lockfiles.append(name)


_PY_EXTS = (".py",)


def _iter_source_files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    """Walk ``root`` for files whose suffix is in ``exts``, pruning noise dirs.

    Shared by the Python and TypeScript extractors (and by scope detection) so the
    skip-dir policy lives in one place.
    """
    # Test trees are pruned on the way down, but scanned when the caller points
    # straight at one (``--scope tests``). Filenames follow the same rule, so an
    # explicit scope keeps surfacing what is inside.
    scoped_into_tests = root.name in _SKIP_DIRS or _is_test_dir(root.name)

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not _is_test_dir(d)]
        for name in filenames:
            if not scoped_into_tests and _is_test_file(name):
                continue
            if name.endswith(exts):
                files.append(Path(dirpath) / name)
    return sorted(files)


def _iter_python_files(root: Path) -> list[Path]:
    """Python source files under ``root`` (``_iter_source_files`` specialised)."""
    return _iter_source_files(root, _PY_EXTS)


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

    def extract(self, path: Path, *, root: Path | None = None) -> McpServer:
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
        # Metadata (deps/lockfiles) lives at the project root, which may be wider
        # than the scan scope when the caller narrowed ``path`` to a subpackage.
        meta_root = root or (path if path.is_dir() else path.parent)
        _load_pyproject(meta_root, server)
        _find_lockfiles(meta_root, server)
        return server

"""Static TypeScript / JavaScript extractor.

Parses MCP server source **without executing it** (no TypeScript compiler, no
``node``) and builds a :class:`~mcpscore.ir.McpServer`. Mirrors
:mod:`mcpscore.extract.python_static` in shape and philosophy: a stdlib-only
heuristic, no new dependency.

Recognises the two official ``@modelcontextprotocol/sdk`` shapes:

* **high-level** ``McpServer``::

      server.tool("greet", "Greet a user", { name: z.string() }, async (args) => ({ ... }));
      server.registerTool(
          "greet",
          { description: "...", inputSchema: z.object({ name: z.string() }) },
          handler,
      );

* **low-level** ``Server``::

      server.setRequestHandler(
          ListToolsRequestSchema,
          async () => ({ tools: [{ name, description, inputSchema }] }),
      );

Tool metadata is read with a small **bracket-matching span scanner** (balance
``()`` / ``[]`` / ``{}`` while honouring ``'…'`` / ``"…"`` / `` `…` `` literals
and ``//`` + ``/* */`` comments) — precise enough for real servers without
pulling in a parser. Zod / Standard-Schema shapes (``z.string()`` …) are mapped
to JSON Schema best-effort.

Every rule is language-agnostic text scanning over
:attr:`McpServer.sources`, so populating ``sources`` with each file's text gives
a TS server secret (MCP102) / RCE (MCP103) / poisoning scanning for free; the
tool name + description + schema we extract here feed MCP101/104/105/106/107.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcpscore.extract.base import Extractor, register_extractor
from mcpscore.extract.python_static import _iter_source_files
from mcpscore.ir import SOURCE_STATIC, McpServer, ServerMeta, Tool

_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
# Declaration / generated bundles are not hand-written server code.
_SKIP_SUFFIXES = (".d.ts", ".d.mts", ".d.cts", ".min.js", ".min.mjs")

# A high-level tool registration: ``<obj>.tool(`` or ``<obj>.registerTool(``.
# The receiver name is unanchored (``server`` / ``mcp`` / ``app`` …).
_HL_RE = re.compile(r"\.\s*(?:tool|registerTool)\s*\(")
# Low-level tool-list handler. Anchored on the actual registration call so a bare
# ``import { ListToolsRequestSchema }`` doesn't re-extract the same tool array.
_LOWLEVEL_RE = re.compile(r"setRequestHandler\s*\(\s*ListToolsRequestSchema")
# ``name: z.<type>`` inside a Zod object / shape.
_ZOD_PROP_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*:\s*z\s*\.\s*([A-Za-z]+)")
_ZOD_TYPE = {
    "string": "string",
    "str": "string",
    "number": "number",
    "num": "number",
    "int": "integer",
    "integer": "integer",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
}
_NPM_LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"}


def _iter_typescript_files(root: Path) -> list[Path]:
    """TS/JS source files under ``root`` via the shared walker, dropping declarations."""
    return [f for f in _iter_source_files(root, _TS_EXTS) if not f.name.endswith(_SKIP_SUFFIXES)]


# --- span scanner (bracket-matching, string/comment aware) --------------------


def _skip_string(text: str, i: int) -> int:
    """Index just past the literal starting at ``i`` (a quote char).

    Handles ``'`` / ``"`` / `` ` `` and backslash escapes. Template-literal
    ``${…}`` is treated opaquely — its inner brackets don't count toward
    balancing, which is exactly what span extraction needs.
    """
    quote = text[i]
    i += 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    return i


def _match_bracket(text: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    """Index of the bracket matching ``text[open_idx]`` (== ``open_ch``), or ``-1``."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_top_level(inner: str) -> list[str]:
    """Split a call body by top-level commas (depth-0 wrt ``()`` / ``[]`` / ``{}``)."""
    args: list[str] = []
    depth = 0
    start = 0
    i = 0
    n = len(inner)
    while i < n:
        c = inner[i]
        if c in "'\"`":
            i = _skip_string(inner, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            args.append(inner[start:i].strip())
            start = i + 1
        i += 1
    tail = inner[start:].strip()
    if tail:
        args.append(tail)
    return args


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of ``offset`` in ``text``."""
    return text.count("\n", 0, offset) + 1


# --- literal / field helpers -------------------------------------------------


_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "`": "`",
    "0": "\0",
    "b": "\b",
    "f": "\f",
}


def _unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _literal_string(a: str) -> str | None:
    """``"foo"`` / ``'foo'`` → ``foo``; anything else → ``None``."""
    a = a.strip()
    if len(a) >= 2 and a[0] in "'\"" and a[-1] == a[0]:
        return _unescape(a[1:-1])
    return None


def _literal_template(a: str) -> str | None:
    """`` `foo` `` (no interpolation) → ``foo``; else ``None``."""
    a = a.strip()
    if len(a) >= 2 and a[0] == "`" and a[-1] == "`":
        return _unescape(a[1:-1])
    return None


def _maybe_string(a: str) -> str | None:
    return _literal_string(a) or _literal_template(a)


def _field_str(text: str, field: str) -> str | None:
    """Value of ``field: "…"`` inside an object literal (best-effort)."""
    m = re.search(r"\b" + re.escape(field) + r"\s*:\s*(['\"])(.*?)\1", text, re.DOTALL)
    return _unescape(m.group(2)) if m else None


def _has_field(text: str, field: str) -> bool:
    return re.search(r"\b" + re.escape(field) + r"\s*:", text) is not None


# --- Zod / JSON-Schema → IR schema -------------------------------------------


def _zod_to_schema(inner: str) -> dict:
    """Map a Zod object/shape body (``a: z.string(), b: z.number()``) to JSON Schema.

    Unknown Zod types are **skipped** (not emitted as empty ``{}``) so MCP104
    never fires "parameter has no type" on something we merely failed to map.
    Discovered properties are all marked ``required`` — that is Zod's default
    (``.optional()`` is the exception), and it keeps MCP104's "no required
    parameters" rule from firing on every TS tool.
    """
    props: dict[str, dict] = {}
    for m in _ZOD_PROP_RE.finditer(inner):
        jt = _ZOD_TYPE.get(m.group(2).lower())
        if jt:
            props[m.group(1)] = {"type": jt}
    schema: dict = {"type": "object", "properties": props}
    if props:
        schema["required"] = list(props.keys())
    return schema


def _schema_from_json_literal(inner: str) -> dict:
    """Best-effort schema from a low-level JSON-Schema object body."""
    props: dict[str, dict] = {}
    pm = re.search(r"\bproperties\s*:\s*", inner)
    if pm:
        brace = inner.find("{", pm.end())
        if brace != -1:
            end = _match_bracket(inner, brace, "{", "}")
            block = inner[brace + 1 : end if end != -1 else len(inner)]
            for m in re.finditer(r'("?)([A-Za-z_$][\w$]*)\1\s*:\s*\{([^{}]*)\}', block):
                tm = re.search(r'type\s*:\s*["\'](\w+)["\']', m.group(3))
                if tm:
                    props[m.group(2)] = {"type": tm.group(1)}
    rm = re.search(r"\brequired\s*:\s*\[([^\]]*)\]", inner)
    required = re.findall(r'["\']([^"\']+)["\']', rm.group(1)) if rm else []
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    elif props:
        schema["required"] = list(props.keys())
    return schema


def _schema_from_value(val: str) -> dict:
    """Interpret a schema-ish expression (Zod object, Zod shape, or JSON-Schema literal)."""
    val = val.strip()
    zo = re.match(r"z\s*\.\s*object\s*\(\s*", val)
    if zo:  # z.object({...})
        brace = val.find("{", zo.end())
        if brace != -1:
            end = _match_bracket(val, brace, "{", "}")
            if end != -1:
                return _zod_to_schema(val[brace + 1 : end])
        return {}
    if val.startswith("{"):
        end = _match_bracket(val, 0, "{", "}")
        inner = val[1 : end if end != -1 else len(val)]
        if re.search(r"\bz\s*\.", inner):  # bare Zod shape { a: z.number() }
            return _zod_to_schema(inner)
        return _schema_from_json_literal(inner)
    return {}


def _field_schema(text: str, field: str) -> dict:
    """Schema following ``field:`` (e.g. ``inputSchema: z.object({...})``)."""
    m = re.search(r"\b" + re.escape(field) + r"\s*:\s*", text)
    if not m:
        return {}
    return _schema_from_value(text[m.end() :])


# --- tool extraction ---------------------------------------------------------


def _is_handler(a: str) -> bool:
    """True if an argument looks like executable code (the trailing handler)."""
    a = a.lstrip()
    return a.startswith(("function", "async function")) or _arrow_index(a) != -1


def _handler_params(a: str) -> list[str] | None:
    """Destructured parameter names a handler reads, for MCP105 drift checking.

    * arrow ``(params) => …`` or ``async (params) => …`` — params are the last
      ``(…)`` group before ``=>``;
    * ``function (params) {…}`` — the first ``(…)`` group.

    Only an *object-destructured* first param (``{a, b}``) is comparable: returns
    the names (``[a, b]``). A bare identifier (``args``) returns ``None`` (we
    can't know what it reads); an empty ``()`` returns ``[]`` (reads nothing).
    Renames (``a: x``), defaults (``a = 1``) and rest (``...rest``) are handled.
    """
    a = a.strip()
    arrow = _arrow_index(a)
    if arrow != -1:
        open_idx = a.rfind("(", 0, arrow)
    else:
        fm = re.match(r"(?:async\s+)?function\s*\*?\s*\(", a)
        if not fm:
            return None
        open_idx = a.find("(", fm.start())
    if open_idx == -1:
        return None
    close = _match_bracket(a, open_idx, "(", ")")
    if close == -1:
        return None
    head = a[open_idx + 1 : close].strip()
    if not head:
        return []  # handler takes no params
    if not head.startswith("{"):
        return None  # bare identifier — can't tell what it reads
    end = _match_bracket(head, 0, "{", "}")
    body = head[1 : end if end != -1 else len(head)]
    names: list[str] = []
    for part in _split_top_level(body):
        token = part.strip()
        if not token or token.startswith("..."):
            continue
        token = token.split("=", 1)[0].strip()  # drop default value
        token = token.split(":", 1)[0].strip()  # drop rename / type annotation
        m = re.match(r"[A-Za-z_$][\w$]*", token)
        if m:
            names.append(m.group(0))
    return names


def _arrow_index(a: str) -> int:
    """Index of the top-level ``=>`` in ``a`` (skipping those inside strings), or -1."""
    i = 0
    n = len(a)
    while i < n:
        c = a[i]
        if c in "'\"`":
            i = _skip_string(a, i)
            continue
        if c == "=" and a[i + 1 : i + 2] == ">":
            return i
        i += 1
    return -1


def _tool_name(arg: str) -> str | None:
    """The tool name from ``args[0]`` — a string literal or a ``{ name: "…" }`` config."""
    s = _maybe_string(arg)
    if s is not None:
        return s
    a = arg.strip()
    if a.startswith("{"):
        return _field_str(a, "name")
    return None


def _extract_highlevel(text: str, posix: str, server: McpServer) -> None:
    """``server.tool(...)`` / ``server.registerTool(...)`` registrations."""
    for m in _HL_RE.finditer(text):
        open_idx = m.end() - 1  # the '(' (regex ends right after it)
        close = _match_bracket(text, open_idx, "(", ")")
        if close == -1:
            continue
        args = _split_top_level(text[open_idx + 1 : close])
        if not args:
            continue
        name = _tool_name(args[0])
        if not name:
            continue

        desc: str | None = None
        schema: dict = {}
        handler: str | None = None
        for arg in args[1:]:
            a = arg.strip()
            if not a:
                continue
            if _is_handler(a):
                handler = a  # captured for MCP105 schema/impl-drift checking
                continue
            # registerTool config object: { description, inputSchema, ... }
            if a.startswith("{") and (_has_field(a, "description") or _has_field(a, "inputSchema")):
                if desc is None:
                    desc = _field_str(a, "description")
                if not schema:
                    schema = _field_schema(a, "inputSchema")
                continue
            s = _maybe_string(a)  # bare description literal
            if s is not None and desc is None:
                desc = s
                continue
            if not schema:  # z.object / Zod shape / JSON-Schema literal
                sc = _schema_from_value(a)
                if sc:
                    schema = sc

        server.tools.append(
            Tool(
                name=name,
                description=desc,
                input_schema=schema,
                source_path=posix,
                line=_line_of(text, m.start()),
                handler_params=_handler_params(handler) if handler else None,
            )
        )


def _extract_lowlevel(text: str, posix: str, server: McpServer) -> None:
    """``setRequestHandler(ListToolsRequestSchema, () => ({ tools: [...] }))``."""
    for m in _LOWLEVEL_RE.finditer(text):
        tail_start = m.end()
        tm = re.search(r"tools\s*:\s*\[", text[tail_start:])
        if not tm:
            continue
        bracket = tail_start + tm.end() - 1  # the '['
        end = _match_bracket(text, bracket, "[", "]")
        if end == -1:
            continue
        arr = text[bracket + 1 : end]
        i = 0
        n = len(arr)
        while i < n:
            if arr[i] == "{":
                obj_start = i  # offset of this tool object's '{' within ``arr``
                obj_end = _match_bracket(arr, obj_start, "{", "}")
                if obj_end == -1:
                    break
                obj = arr[obj_start + 1 : obj_end]
                i = obj_end + 1
                name = _field_str(obj, "name")
                if not name:
                    continue
                # Line of the object itself (not the handler anchor), so several
                # anchors pointing at the same array de-duplicate to one tool.
                server.tools.append(
                    Tool(
                        name=name,
                        description=_field_str(obj, "description"),
                        input_schema=_field_schema(obj, "inputSchema"),
                        source_path=posix,
                        line=_line_of(text, bracket + 1 + obj_start),
                    )
                )
            else:
                i += 1


def _extract_file(path: Path, server: McpServer) -> None:
    # ``errors="replace"`` so one oddly-encoded file can't abort the whole scan.
    text = path.read_text(encoding="utf-8", errors="replace")
    posix = path.as_posix()
    server.sources[posix] = text
    _extract_highlevel(text, posix, server)
    _extract_lowlevel(text, posix, server)


# --- project metadata (dependencies, lockfiles) ------------------------------


def _load_package_json(root: Path, server: McpServer) -> None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(section)
        if isinstance(deps, dict):
            for name, spec in deps.items():
                if isinstance(name, str):
                    server.dependencies[name] = str(spec)
    if server.dependencies:
        server.dep_file = str(pkg)  # provenance for `--fix`


def _find_npm_lockfiles(root: Path, server: McpServer) -> None:
    for name in _NPM_LOCKFILES:
        if (root / name).is_file():
            server.lockfiles.append(name)


@register_extractor
class TypescriptExtractor(Extractor):
    """Extract tools from TypeScript/JavaScript MCP server source."""

    language = "typescript"

    def applies_to(self, path: Path) -> bool:
        if path.is_file():
            return path.suffix in _TS_EXTS and not path.name.endswith(_SKIP_SUFFIXES)
        if path.is_dir():
            # Parity with PythonExtractor: any TS/JS source present matches. A
            # signal-free tree (e.g. a test dir holding only a fake secret) still
            # scans its ``sources`` text so MCP102/103 can fire.
            return any(True for _ in _iter_typescript_files(path))
        return False

    def extract(self, path: Path, *, root: Path | None = None) -> McpServer:
        files = [path] if path.is_file() else _iter_typescript_files(path)
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
        # De-duplicate identical registrations (same name + site): a tool can be
        # matched by more than one heuristic span, and the low-level array may be
        # re-scanned across handler occurrences.
        seen: set[tuple[str, str | None, int | None]] = set()
        unique: list[Tool] = []
        for t in server.tools:
            key = (t.name, t.source_path, t.line)
            if key in seen:
                continue
            seen.add(key)
            unique.append(t)
        server.tools = unique
        # Metadata lives at the project root, which may be wider than the scan
        # scope when the caller narrowed ``path`` to a subdirectory.
        meta_root = root or (path if path.is_dir() else path.parent)
        _load_package_json(meta_root, server)
        _find_npm_lockfiles(meta_root, server)
        return server

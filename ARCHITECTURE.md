# Architecture

`mcpscore` is a four-stage pipeline: **extract → lint → score → report**. Each stage is independently pluggable.

```
   PATH / --manifest / --runtime --command
        │
        ▼
┌───────────────┐   @register_extractor
│  Extractors   │   PythonExtractor (AST) · TypescriptExtractor (span scan) · ManifestExtractor (tools/list JSON)
│               │   + runtime.py: --runtime spawns the server → tools/list → manifest.from_tools()
└───────┬───────┘
        │  McpServer (the IR)
        ▼
┌───────────────┐   @register_rule
│    Rules      │   MCP101..MCP109  →  Diagnostic{rule_id, severity, file, line, …}
└───────┬───────┘   run_all(): applies every rule, sorts errors-first
        │  doc.diagnostics
        ▼
┌───────────────┐
│    Score      │   deductions by severity; any error → cap at 60 → 0..100 + grade
└───────┬───────┘
        │  ScoreResult
        ▼
┌───────────────┐
│    Report     │   plain · json · github · sarif   (+ badge SVG)
└───────────────┘
```

## The IR — `McpServer`

Every extractor emits one, every rule consumes one. Defined in `src/mcpscore/ir.py`.

- `meta: ServerMeta` — `name`, `language`, `path`, version, repo.
- `tools: list[Tool]` — `name`, `description`, `input_schema` (JSON Schema), `source_path`, `line`, `runtime_only` (True for manifest-extracted tools).
- `resources`, `prompts` — placeholders (v0.2 surface).
- `dependencies: list[str]`, `lockfiles: list[str]` — for supply-chain rules (MCP108).
- `sources: dict[str, str]` — path → file text, for source-text rules (MCP102/MCP103). Manifest/runtime modes have none, which is why those rules gate on `doc.sources`.
- `diagnostics: list[Diagnostic]` — filled by `run_all`.
- `source_mode` — `static` (parsed from source), `manifest` (`--manifest` file), or `runtime` (`--runtime` live capture). The verdict engine treats only `static` + zero tools as UNKNOWN.
- `.has_errors` / `.errors` — convenience views over diagnostics.

`Severity` constants (`SEVERITY_ERROR/WARNING/INFO`), risk tiers (`RISK_CRITICAL/HIGH/MEDIUM/LOW` + `RISK_WEIGHT`), `ERROR_SCORE_CAP = 60`, and `severity_rank()` live here too.

## Extractors

`Extractor` (`extract/base.py`) is an ABC: `applies_to(path) -> bool` and `extract(path) -> McpServer`. `extractor_for(path)` returns the first registered extractor whose `applies_to` matches (builtins first).

- **`PythonExtractor`** (`extract/python_static.py`) — walks `.py` files (skipping `__pycache__`, `.venv`, `.git`, `node_modules`, `build`, `tests`/`fixtures`), finds functions decorated with `@mcp.tool` / `@server.tool` / bare `@tool`, and lifts: decorator `name=`/`description=` kwargs, the docstring, and type hints. `_annotation_to_schema` maps AST annotation nodes to JSON Schema (`str→string`, `int→integer`, `float→number`, `bool→boolean`, `list[X]→array`, `dict[K,V]→object`, `Optional/Union/PEP-604` → nullable; custom types → `{}`). It also reads a nearby `pyproject.toml` for dependencies and finds lockfiles.
- **`TypescriptExtractor`** (`extract/typescript_static.py`) — walks `.ts`/`.tsx`/`.js`/`.jsx`/`.mjs`/`.cjs`/… (skipping `*.d.ts`, minified bundles, and the same noise dirs) and finds tools via a **bracket-matching span scanner** (no parser dep): the high-level `server.tool("name", …)` / `server.registerTool("name", {description, inputSchema}, handler)` forms **and** the low-level `setRequestHandler(ListToolsRequestSchema, … → tools:[…])` form. Zod shapes (`z.string()` …) are mapped to JSON Schema. It reads a nearby `package.json` for dependencies and finds npm lockfiles. Registered after `PythonExtractor`, so Python wins mixed repos and TS wins pure-TS trees.
- **`ManifestExtractor`** (`extract/manifest.py`) — reads a captured `tools/list` dump (raw `{tools: [...]}` or JSON-RPC `{result: {tools: [...]}}`), language-agnostic. Tools get `runtime_only=True`. The per-tool builder (`_tool_from_entry`) and `McpServer` assembly (`_build`) are shared with `from_tools()` so a file dump and a live capture produce the same IR.
- **`runtime.py`** (not an extractor — an opt-in capture path) — `check --runtime --command "<launch>"` spawns the server (`asyncio.create_subprocess_exec`, `shell=False`, argv via `shlex.split`), runs the MCP JSON-RPC stdio handshake (`initialize` → `notifications/initialized` → `tools/list`, newline-delimited), and feeds the captured tools to `manifest.from_tools()` (`source_mode=SOURCE_RUNTIME`, `meta.name`/`version` from the server's `initialize` `serverInfo`). Bounded per-step timeouts + guaranteed terminate→kill; stderr drained in the background so a chatty server can't deadlock on a full pipe. **No OS-level sandbox** — opt-in, trusted/container only; mutual-exclusive with `--manifest` and requires `--command`.

## Rules

`Rule` (`rules/base.py`) is an ABC: `applies(doc) -> bool` (default True) and `check(doc) -> Iterable[Diagnostic]`. `@register_rule` adds a subclass to the registry; `run_all(doc)` instantiates each applicable rule, collects findings, sorts them errors-first (`-severity_rank`), and mirrors them onto `doc.diagnostics`.

Builtins live in `rules/builtin/`:
- `descriptions.py` — MCP101 (poisoning: 8 injection-signature regexes + hidden Unicode `Cf` chars), MCP107 (hygiene).
- `source.py` — MCP102 (secrets), MCP103 (dangerous capabilities). Gated on `doc.sources`.
- `schema.py` — MCP104 (weak schema), MCP106 (JSON-Schema compatibility), MCP105 (schema/handler drift; compares `tool.handler_params`).
- `supply.py` — MCP108 (unpinned deps, no lockfile; pip **and** npm semver).
- `transport.py` — MCP109 (HTTP/SSE transport without TLS or auth). Gated on `doc.sources`.

## Score

`score(doc)` (`score.py`) counts findings by severity, applies deductions (`error` −20, `warning` −6, `info` −1), and if any error is present caps the result at `ERROR_SCORE_CAP` (60) — so a server with a leaked secret or poisoned tool can never score above D. Returns a frozen `ScoreResult{score, errors, warnings, infos, capped}` with a `.grade` (A–F) and `.passed(fail_under)`.

## Report & badge

`report/__init__.py` dispatches by format name to one of `plain`/`json`/`github`/`sarif`; every formatter shares the signature `render(diags, doc, score_result) -> str`. `badge.badge_svg(score_result)` renders a flat shields-style SVG, color chosen by grade.

## Extension points

- **Add a rule** — subclass `Rule`, decorate `@register_rule`, implement `check`. For an external package, add an entry-point under `mcpscore.rules`.
- **Add an extractor** — subclass `Extractor`, decorate `@register_extractor`, implement `applies_to` + `extract`. Entry-point: `mcpscore.extractors`.

See `CONTRIBUTING.md` for copy-pasteable examples.

# mcpscore

**Static linter + 0–100 scorecard for MCP servers.** `mcpscore` scans an MCP server's source (or a captured `tools/list` manifest) and flags tool poisoning, leaked secrets, dangerous capabilities and weak schemas — locally, deterministically, in CI. One score, one badge.

## Install

```bash
uv tool install mcpscore
# or: pip install mcpscore
```

## Commands

| Command | Purpose |
| --- | --- |
| `mcpscore scan [PATH] [--manifest FILE] [-f plain\|json\|github\|sarif] [--check]` | Lint a server; `--check` exits 1 on any ERROR (CI gate). |
| `mcpscore score [PATH] [--manifest FILE] [--fail-under N]` | Print the 0–100 score; exit 1 below `--fail-under`. |
| `mcpscore badge [PATH \| --score N] [-o FILE]` | Render an SVG score badge. |
| `mcpscore version` | Print the version. |

## How it works

- **Static by default.** The Python extractor walks `.py` files, finds `@mcp.tool` / `@server.tool` decorators, and lifts `name`, the docstring (→ `description`) and type hints (→ JSON Schema) from the AST — **no imports, no execution**. Deterministic, CI-safe, no false trust in what the server reports at runtime.
- **IR = `McpServer`.** Every extractor emits one, every rule consumes one. `meta`, `tools[]` (`name`/`description`/`input_schema`/`source_path`/`line`/`runtime_only`), `resources[]`, `prompts[]`, `dependencies`, `sources: dict[path, text]`, `lockfiles`, `diagnostics[]`.
- **Rules → Diagnostics.** Each rule sees the IR and yields `Diagnostic{rule_id, severity, message, tool, file, line, col}`. `run_all` sorts errors-first and mirrors onto `doc.diagnostics`.
- **Score.** Findings collapse to 0–100: `error` −20, `warning` −6, `info` −1, clamped `[0,100]`. **Any `error` caps the score at 60** so a leaked secret or poisoned tool can't be diluted into a green grade.
- **Plugins.** Subclass `Rule` or `Extractor`, decorate with `@register_rule` / `@register_extractor`, and (for external packages) declare an entry-point in `mcpscore.rules` / `mcpscore.extractors`. See `CONTRIBUTING.md`.

## Rules (v0.1)

| ID | Scope | Rule |
| --- | --- | --- |
| MCP101 | tool `description` | prompt-injection signatures / hidden unicode (tool poisoning) |
| MCP102 | source text | secrets & API keys (regex) |
| MCP103 | source text | dangerous capabilities (`os.system`, `eval`, `exec`, `pickle.loads`, `shell=True`) |
| MCP104 | tool schema | weak schema (no `required`, empty `{}` property) |
| MCP106 | tool schema | JSON-Schema incompatibilities (`$ref`/`oneOf`/`anyOf`/`allOf`, missing `type`) |
| MCP107 | tool `description` | missing or oversized (>4096 chars) |
| MCP108 | dependencies | unpinned deps with no lockfile |

MCP105 (schema/impl drift) and MCP109 (transport auth/TLS) are deferred to v0.2 (need runtime/config input the static core lacks).

## Build & test

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest                       # 70 tests, ~94% coverage
uv run mcpscore scan tests/fixtures/servers/clean      # dogfood: 100/100, exit 0
uv run mcpscore scan tests/fixtures/servers/leaky --check   # dogfood: errors, exit 1
```

## Layout

```
src/mcpscore/   cli, ir, score, badge
                 extract/{base,python_static,manifest}  rules/{base,builtin/*}
                 report/{plain,json,github,sarif}
tests/          unit (ir, extract, rules, score, report) + cli e2e + fixtures/servers/
```

## License

MIT.

# mcpscore

**Static linter + 0–100 scorecard for MCP servers.** `mcpscore` scans an MCP server's source (or a captured `tools/list` manifest) and flags tool poisoning, leaked secrets, dangerous capabilities, weak schemas and more — **locally, deterministically, in CI**. One score, one badge.

> MCP is the fastest-growing dev protocol since GraphQL (~97M SDK downloads/month), yet 7%+ of servers ship with vulnerabilities and the OWASP MCP Top 10 is a list, not a tool. `mcpscore` is the missing `npm audit` + OpenSSF Scorecard for MCP — static, local-first, OSS.

## Status

✅ **v0.1.0** — Python static extractor + manifest extractor, rules MCP101/102/103/104/106/107/108, CLI (`scan`/`score`/`badge`/`version`), plain/json/github/sarif reports, 0–100 score with error cap, SVG badge, plugin API. 70 tests, 94% coverage.

TypeScript extraction, runtime `tools/list` capture, and rules MCP105 (schema/impl drift) / MCP109 (transport auth) land in v0.2.

## Install

```bash
uv tool install mcpscore
# or: pip install mcpscore
```

Requires Python ≥ 3.10.

## Quick start

```bash
# Lint a FastMCP server from source — findings + score
mcpscore scan path/to/my-mcp-server

# CI gate: fail the build on any ERROR finding
mcpscore scan path/to/my-mcp-server --check -f github

# Just the score (0–100), fail below a bar
mcpscore score path/to/my-mcp-server --fail-under 80

# No source? Lint a captured tools/list dump from any language
mcpscore scan --manifest tools-list.json

# Embed a badge in your README
mcpscore badge path/to/my-mcp-server -o docs/score.svg
```

## Commands

| Command | Purpose |
| --- | --- |
| `mcpscore scan [PATH] [--manifest FILE] [-f plain\|json\|github\|sarif] [--check]` | Lint a server and print findings. `--check` exits 1 on any ERROR (CI gate). |
| `mcpscore score [PATH] [--manifest FILE] [--fail-under N]` | Print the 0–100 score and grade; exit 1 below `--fail-under`. |
| `mcpscore badge [PATH \| --score N] [-o FILE]` | Render an SVG score badge (`-o -` for stdout). |
| `mcpscore version` | Print the version. |

## Rules

Each finding is a `Diagnostic` with a severity (`error`/`warning`/`info`). **Any `error` caps the score at 60**, so a leaked secret or poisoned tool can never be diluted into a green grade.

| ID | OWASP MCP | Rule | Severity |
| --- | --- | --- | --- |
| MCP101 | Tool Poisoning | hidden instructions in a tool `description` ("ignore previous", exfiltrate-to-URL, hidden format/bidi chars) | error |
| MCP102 | Token/Secret Exposure | secrets/tokens/API keys in source (regex: private keys, `sk-`, AWS, GitHub, GitLab, Slack, Google, hardcoded creds) | error |
| MCP103 | Excess Permissions (MCP04) | dangerous capabilities: `os.system`, `eval`/`exec`, `pickle.loads`, `subprocess(..., shell=True)` | error |
| MCP104 | — (hygiene) | weak schema: no `required`, or a property with an empty `{}` schema | warning |
| MCP106 | — (compat) | JSON-Schema incompatibilities that break Cursor/ChatGPT (`$ref`/`oneOf`/`anyOf`/`allOf`, missing `type`) | warning |
| MCP107 | — (context) | missing or oversized `description` (eats the model's context budget) | warning |
| MCP108 | Supply-Chain (MCP05) | unpinned dependencies with no lockfile | warning |

> Roadmap: MCP105 (schema/implementation drift) and MCP109 (transport auth / TLS) arrive in v0.2 — both need runtime or config input v0.1's static core doesn't have yet.

## Score & grades

| Grade | Score | Meaning |
| --- | --- | --- |
| **A** | 90–100 | Clean |
| **B** | 80–89 | Minor warnings |
| **C** | 70–79 | Some hygiene debt |
| **D** | 60–69 | Serious — errors present (capped) |
| **F** | 0–59 | Critical — errors present (capped) |

Deductions: `error` = −20, `warning` = −6, `info` = −1, clamped to `[0, 100]`.

## CI

```yaml
# .github/workflows/mcp.yml
name: mcpscore
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv tool install mcpscore
      # GitHub annotations + SARIF-friendly; fails on any ERROR
      - run: mcpscore scan ./src --check -f github
      # Optional: fail below a score bar
      - run: mcpscore score ./src --fail-under 80
```

## How it works

1. **Extract.** `PythonExtractor` walks `.py` files, finds `@mcp.tool` / `@server.tool` decorators, and lifts `name`, the docstring (→ `description`) and type hints (→ JSON Schema) straight from the AST — **no imports, no execution**. `ManifestExtractor` parses a captured `tools/list` JSON dump for servers in any language.
2. **Lint.** Each rule sees the resulting `McpServer` IR and emits `Diagnostic`s.
3. **Score.** Findings collapse to a 0–100 score with an error cap (mirrors OpenSSF Scorecard's shape).
4. **Report.** `plain`, `json`, `github` annotations, or `sarif` (for GitHub code scanning).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline and [CONTRIBUTING.md](CONTRIBUTING.md) to add a rule or extractor in one file.

## Why mcpscore

- **Static, not runtime.** No need to start the server or trust what it reports at runtime — parse definitions from source. Deterministic and CI-safe.
- **MCP-semantic.** Knows about tool poisoning, schema compatibility, over-permissive tools — things generic SAST and OpenSSF Scorecard can't see.
- **Source-level locations.** Findings point at `file:line`, not anonymous runtime entries.
- **Plugin-friendly.** Add a rule or an extractor by subclassing + one decorator. Entry-points let external packages extend `mcpscore` without forking.

## Dogfood

Scanned against the official [`modelcontextprotocol/python-sdk`](https://github.com/modelcontextprotocol/python-sdk) example servers:

| Server | Score | Findings |
| --- | --- | --- |
| `everything-server` | **82/100 (B)** | 3 warnings — an untyped `region` param, an all-optional schema, unpinned deps |
| `examples/mcpserver` | **58/100 (F)** | 7 warnings — missing descriptions, untyped Pydantic-model params |

(FastMCP's framework-injected `ctx: Context` parameter is correctly excluded from every tool's schema — the same way the SDK itself does it — so it doesn't generate noise.)

## Roadmap

- **v0.2** — TypeScript static extractor, runtime `tools/list` capture, rules MCP105/109 + shadow endpoints, hosted badge API + a public leaderboard of top MCP servers.
- **v1.0** — freeze the plugin API (semver), `--fix` for trivial rules, pre-commit hook, PyPI trusted publishing, registry integrations (Glama/Smithery).

## License

MIT.

# mcpscore

**Static linter + 0–100 scorecard for MCP servers.** `mcpscore` scans an MCP server's source (or a captured `tools/list` manifest) and flags tool poisoning, leaked secrets, dangerous capabilities, weak schemas and more — **locally, deterministically, in CI**. Point it at a GitHub URL or a local path and get a plain-language verdict — 🟢 ok / 🟡 caution / 🔴 danger — plus a 0–100 score and an SVG badge.

> MCP is the fastest-growing dev protocol since GraphQL (~97M SDK downloads/month), yet 7%+ of servers ship with vulnerabilities and the OWASP MCP Top 10 is a list, not a tool. `mcpscore` is the missing `npm audit` + OpenSSF Scorecard for MCP — static, local-first, OSS.

## Status

✅ **v0.1.0** — Python static extractor + manifest extractor, rules MCP101/102/103/104/106/107/108, `scan`/`score`/`badge`/`version`, plain/json/github/sarif reports, 0–100 score with error cap, SVG badge, plugin API. 73 tests, 94% coverage.

🚧 **dev (→ v0.2):** friendly `check` command — point at a **GitHub URL** or a local path, get a traffic-light verdict (🟢/🟡/🔴/⚪) + a plain-language recommendation; new `card` report format. 120+ tests.

TypeScript static extraction, runtime `tools/list` capture, and rules MCP105 (schema/impl drift) / MCP109 (transport auth) land in v0.2.

## Install

```bash
uv tool install mcpscore
# or: pip install mcpscore
```

Requires Python ≥ 3.10.

## Quick start

```bash
# Is this MCP server safe to install? Point mcpscore at a GitHub URL or a local path.
mcpscore check https://github.com/owner/repo
mcpscore check path/to/my-mcp-server

# Verdict + the full finding list
mcpscore check path/to/my-mcp-server --details

# Not a Python server? Hand mcpscore a captured tools/list dump (any language)
mcpscore check --manifest tools-list.json

# --- power users / CI -----------------------------------------------------
# Lint and print findings (CI gate: --check exits 1 on any ERROR)
mcpscore scan path/to/my-mcp-server --check -f github
# Just the 0–100 score, fail below a bar
mcpscore score path/to/my-mcp-server --fail-under 80
# Embed an SVG score badge in your README
mcpscore badge path/to/my-mcp-server -o docs/score.svg
```

## Commands

| Command | Purpose |
| --- | --- |
| `mcpscore check <URL \| PATH> [--manifest FILE] [--details\|-v] [--fail-under N]` | **Friendly safety verdict** (🟢/🟡/🔴/⚪) + recommendation. Clones a GitHub URL automatically; exits 1 on 🔴 danger or below `--fail-under`. |
| `mcpscore scan [PATH] [--manifest FILE] [-f plain\|json\|github\|sarif\|card] [--check]` | Lint a server and print findings. `--check` exits 1 on any ERROR (CI gate). |
| `mcpscore score [PATH] [--manifest FILE] [--fail-under N]` | Print the 0–100 score and grade; exit 1 below `--fail-under`. |
| `mcpscore badge [PATH \| --score N] [-o FILE]` | Render an SVG score badge (`-o -` for stdout). |
| `mcpscore version` | Print the version. |

## What the verdict means

`mcpscore check` turns findings into a traffic-light verdict instead of a raw score:

| Verdict | When | Exit | What to do |
| --- | --- | --- | --- |
| 🟢 **OK** | nothing found | 0 | Safe to add to Claude Code. |
| 🟡 **CAUTION** | no errors, but warnings (weak schemas, unpinned deps, …) | 0 | Usable — mind the listed weaknesses. |
| 🔴 **DANGER** | any error (tool poisoning, leaked secrets, RCE) | 1 | **Do not install.** |
| ⚪ **UNKNOWN** | no MCP tools found statically (unsupported language, or tools built at runtime) | 0 | Can't check statically — capture `tools/list` and re-run with `--manifest`. |

The numeric score (0–100, shown as a secondary detail) still follows the error-cap rule below: any error caps it at 60. `--fail-under N` adds a CI gate that is independent of the verdict (it can turn a 🟡/🟢 into an exit-1 without changing the displayed verdict).

> **Languages:** v0.2 checks **Python and TypeScript** statically (FastMCP `@mcp.tool` and the TS SDK's `server.tool(...)` / `registerTool(...)` / low-level `ListToolsRequestSchema` shapes). Servers in other languages — or tools built dynamically at runtime — still return ⚪ UNKNOWN; capture `tools/list` and run `mcpscore check --manifest dump.json`.

## Rules

Each finding is a `Diagnostic` with a severity (`error`/`warning`/`info`). **Any `error` caps the score at 60**, so a leaked secret or poisoned tool can never be diluted into a green grade.

| ID | OWASP MCP | Rule | Severity |
| --- | --- | --- | --- |
| MCP101 | Tool Poisoning | hidden instructions in a tool `description` ("ignore previous", exfiltrate-to-URL, hidden format/bidi chars) | error |
| MCP102 | Token/Secret Exposure | secrets/tokens/API keys in source (regex: private keys, `sk-`, AWS, GitHub, GitLab, Slack, Google, hardcoded creds) | error |
| MCP103 | Excess Permissions (MCP04) | dangerous capabilities: `os.system`, `eval`/`exec`, `pickle.loads`, `subprocess(..., shell=True)` | error |
| MCP104 | — (hygiene) | weak schema: no `required`, or a property with an empty `{}` schema | warning |
| MCP105 | — (correctness) | schema/implementation drift: a tool's declared `inputSchema` disagrees with its handler's parameters | warning |
| MCP106 | — (compat) | JSON-Schema incompatibilities that break Cursor/ChatGPT (`$ref`/`oneOf`/`anyOf`/`allOf`, missing `type`) | warning |
| MCP107 | — (context) | missing or oversized `description` (eats the model's context budget) | warning |
| MCP108 | Supply-Chain (MCP05) | unpinned dependencies with no lockfile (pip **and** npm — `^`/`~`/`>=`/`*` drift) | warning |
| MCP109 | — (transport) | HTTP/SSE transport exposed without TLS or authentication | warning |

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

- **v0.2** — scope URL clones to the server entry point (no whole-repo false positives from `tests/`), TypeScript static extractor (the big win — makes `check` work for the majority of servers), rules MCP105/109, opt-in runtime `tools/list` capture. Full plan: [`docs/v0.2-plan.md`](docs/v0.2-plan.md).
- **v1.0** — freeze the plugin API (semver), `--fix` for trivial rules, pre-commit hook, PyPI trusted publishing, hosted badge API + leaderboard, registry integrations (Glama/Smithery).

## License

MIT.

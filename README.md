# mcpxray

**Static linter + 0–100 scorecard for MCP servers.** `mcpxray` scans an MCP server's source (or a captured `tools/list` manifest) and flags tool poisoning, leaked secrets, dangerous capabilities, weak schemas and more — **locally, deterministically, in CI**. Point it at a GitHub URL or a local path and get a plain-language verdict — 🟢 ok / 🟡 caution / 🔴 danger — plus a 0–100 score and an SVG badge.

> MCP is the fastest-growing dev protocol since GraphQL (~97M SDK downloads/month), yet 7%+ of servers ship with vulnerabilities and the OWASP MCP Top 10 is a list, not a tool. `mcpxray` is the missing `npm audit` + OpenSSF Scorecard for MCP — static, local-first, OSS.

## Status

✅ **v1.0.0** — stable public API. Python + TypeScript static extractors, manifest extractor, opt-in runtime `tools/list` capture, rules **MCP101–109** (full OWASP MCP Top-10 mapping), `check`/`scan`/`score`/`badge`/`version`, plain/json/github/sarif/card reports, 0–100 score with error cap, SVG badge, `--fix`/`--diff` for MCP108, pre-commit hook, frozen plugin API (`__all__` + SemVer policy), tokenless PyPI trusted publishing. 224 tests.

## Install

```bash
uv tool install mcpxray-cli
# or: pip install mcpxray-cli
```

The PyPI distribution is `mcpxray-cli` (the name `mcpxray` is blocked on PyPI by an unrelated project); the command it installs is still `mcpxray`.

Requires Python ≥ 3.10.

## Quick start

```bash
# Is this MCP server safe to install? Point mcpxray at a GitHub URL or a local path.
mcpxray check https://github.com/owner/repo
mcpxray check path/to/my-mcp-server

# Verdict + the full finding list
mcpxray check path/to/my-mcp-server --details

# Not a Python server? Hand mcpxray a captured tools/list dump (any language)
mcpxray check --manifest tools-list.json

# ...or spawn the server and let mcpxray capture tools/list live (any language)
mcpxray check --runtime --command "python -m my_mcp_server"

# --- power users / CI -----------------------------------------------------
# Lint and print findings (CI gate: --check exits 1 on any ERROR)
mcpxray scan path/to/my-mcp-server --check -f github
# Just the 0–100 score, fail below a bar
mcpxray score path/to/my-mcp-server --fail-under 80
# Embed an SVG score badge in your README
mcpxray badge path/to/my-mcp-server -o docs/score.svg
```

## Commands

| Command | Purpose |
| --- | --- |
| `mcpxray check <URL \| PATH> [--manifest FILE] [--runtime --command CMD] [--details\|-v] [--fail-under N]` | **Friendly safety verdict** (🟢/🟡/🔴/⚪) + recommendation. Clones a GitHub URL automatically; exits 1 on 🔴 danger or below `--fail-under`. |
| `mcpxray scan [PATH] [--manifest FILE] [--runtime --command CMD] [-f plain\|json\|github\|sarif\|card] [--check] [--fix] [--diff]` | Lint a server and print findings. `--check` exits 1 on any ERROR (CI gate); `--fix` pins unpinned deps in place, `--diff` previews (local source only). |
| `mcpxray score [PATH] [--manifest FILE] [--runtime --command CMD] [--fail-under N]` | Print the 0–100 score and grade; exit 1 below `--fail-under`. |
| `mcpxray badge [PATH \| --score N] [-o FILE]` | Render an SVG score badge (`-o -` for stdout). |
| `mcpxray version` | Print the version. |

## What the verdict means

`mcpxray check` turns findings into a traffic-light verdict instead of a raw score:

| Verdict | When | Exit | What to do |
| --- | --- | --- | --- |
| 🟢 **OK** | nothing found | 0 | Safe to add to Claude Code. |
| 🟡 **CAUTION** | no errors, but warnings (weak schemas, unpinned deps, …) | 0 | Usable — mind the listed weaknesses. |
| 🔴 **DANGER** | any error (tool poisoning, leaked secrets, RCE) | 1 | **Do not install.** |
| ⚪ **UNKNOWN** | no MCP tools found statically (unsupported language, or tools built at runtime) | 0 | Can't check statically — capture `tools/list` (`--manifest`) or spawn the server (`--runtime --command`). |

The numeric score (0–100, shown as a secondary detail) still follows the error-cap rule below: any error caps it at 60. `--fail-under N` adds a CI gate that is independent of the verdict (it can turn a 🟡/🟢 into an exit-1 without changing the displayed verdict).

> **Languages:** mcpxray checks **Python and TypeScript** statically (FastMCP `@mcp.tool` and the TS SDK's `server.tool(...)` / `registerTool(...)` / low-level `ListToolsRequestSchema` shapes). Servers in other languages — or tools built dynamically at runtime — still return ⚪ UNKNOWN; capture `tools/list` (`mcpxray check --manifest dump.json`), or spawn the server and let mcpxray capture it live (`mcpxray check --runtime --command '<launch>'`).

## Runtime capture (`--runtime --command`)

When source isn't parseable (compiled, 3rd-party, or tools built dynamically), `--runtime` **spawns the server, performs the MCP JSON-RPC handshake over stdio (`initialize` → `notifications/initialized` → `tools/list`), and feeds the captured tools through the same rules**. It's strictly opt-in and needs an explicit launch command:

```bash
mcpxray check --runtime --command "python -m my_mcp_server"
mcpxray check --runtime --command "node dist/index.js" path/to/server   # cwd = the path
```

> ⚠️ **`--runtime` executes the server under inspection.** It is opt-in, runs the server with a bounded lifetime (timeouts + guaranteed teardown), and parses its response defensively — but provides **no OS-level sandbox** (no filesystem/network isolation). Only point it at servers you trust; for untrusted servers, run mcpxray inside a container or VM. Prefer `--manifest` when you already have a captured `tools/list`.

Runtime-captured tools carry no source text, so the source-scanning rules (MCP102 secrets / MCP103 RCE / MCP105 drift / MCP109 transport) can't fire — but schema and description rules (MCP104/106/107) still run on the captured definitions.

## Auto-fix (`scan --fix` / `--diff`)

The one rule that's mechanically, unambiguously fixable is **MCP108** (unpinned dependencies): `scan --fix` pins a floating spec to its concrete floor version — `requests>=2.30.0` → `requests==2.30.0` (pip), `"zod": "^1.2.3"` → `"zod": "1.2.3"` (npm). It edits `pyproject.toml` / `package.json` in place (atomically); `--diff` prints the same changes as a unified diff and writes nothing.

```bash
mcpxray scan path/to/server --diff     # preview (exits 1 if changes are pending — CI-friendly)
mcpxray scan path/to/server --fix      # apply in place
```

What it does **not** touch:

- **No floor to pin** (`*`, `latest`, a bare `flask`, `>=2` with no patch) → skipped, left for you to resolve against a registry. mcpxray never invents a version.
- **Specs with extras/env markers** (`pkg[extra]>=1.2.3`, `pkg>=1.2.3 ; python_version>'3'`) → skipped (rewriting them textually is unsafe).
- **Every other rule** (MCP101–107, MCP109) → not auto-fixable; these need human judgment (a leaked secret isn't "fixed" by deleting it).

`--fix`/`--diff` are **static-source-only** — they rewrite files in place, so they reject `--manifest`, `--runtime`, and URL targets (point them at a local path). Every edit is a literal, uniquely-anchored replacement, so an ambiguous match is skipped rather than applied wrongly. Re-run `scan` after `--fix` to confirm the score improved.

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
name: mcpxray
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv tool install mcpxray-cli
      # GitHub annotations + SARIF-friendly; fails on any ERROR
      - run: mcpxray scan ./src --check -f github
      # Optional: fail below a score bar
      - run: mcpxray score ./src --fail-under 80
```

## Pre-commit hook

Lint on every commit from any MCP-server repo. Add `mcpxray` to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/cloudroad-io/mcpxray
    rev: v1.0.0          # pin to a release tag
    hooks:
      - id: mcpxray
        args: ["./src"]  # path to your server source
```

The hook runs `mcpxray scan --check <path>` and fails the commit on any ERROR (tool poisoning, leaked secrets, RCE). Requires the `mcpxray-cli` distribution on PyPI; if you install it locally instead (`uv tool install mcpxray-cli`), set `language: system` on the hook.

## How it works

1. **Extract.** `PythonExtractor` walks `.py` files, finds `@mcp.tool` / `@server.tool` decorators, and lifts `name`, the docstring (→ `description`) and type hints (→ JSON Schema) straight from the AST — **no imports, no execution**. `ManifestExtractor` parses a captured `tools/list` JSON dump for servers in any language. For servers you can run, `--runtime --command` spawns it and captures `tools/list` live (`runtime.py`).
2. **Lint.** Each rule sees the resulting `McpServer` IR and emits `Diagnostic`s.
3. **Score.** Findings collapse to a 0–100 score with an error cap (mirrors OpenSSF Scorecard's shape).
4. **Report.** `plain`, `json`, `github` annotations, or `sarif` (for GitHub code scanning).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline and [CONTRIBUTING.md](CONTRIBUTING.md) to add a rule or extractor in one file.

## Why mcpxray

- **Static, not runtime.** No need to start the server or trust what it reports at runtime — parse definitions from source. Deterministic and CI-safe.
- **MCP-semantic.** Knows about tool poisoning, schema compatibility, over-permissive tools — things generic SAST and OpenSSF Scorecard can't see.
- **Source-level locations.** Findings point at `file:line`, not anonymous runtime entries.
- **Plugin-friendly.** Add a rule or an extractor by subclassing + one decorator. Entry-points let external packages extend `mcpxray` without forking.

## Dogfood

Scanned against the official [`modelcontextprotocol/python-sdk`](https://github.com/modelcontextprotocol/python-sdk) example servers:

| Server | Score | Findings |
| --- | --- | --- |
| `everything-server` | **82/100 (B)** | 3 warnings — an untyped `region` param, an all-optional schema, unpinned deps |
| `examples/mcpserver` | **58/100 (F)** | 7 warnings — missing descriptions, untyped Pydantic-model params |

(FastMCP's framework-injected `ctx: Context` parameter is correctly excluded from every tool's schema — the same way the SDK itself does it — so it doesn't generate noise.)

## Roadmap

- **v0.2** — scope URL clones to the server entry point, TypeScript static extractor, rules MCP105/109, opt-in runtime `tools/list` capture (`--runtime --command`). ✅ shipped.
- **v1.0** — frozen plugin API (SemVer), `--fix`/`--diff`, pre-commit hook, GitHub Actions CI, PyPI trusted publishing. ✅ shipped (v1.0.0).
- **Later** (needs external services/accounts): hosted badge API + leaderboard (hosting), registry integrations (Glama/Smithery API keys). Full history: [`docs/v0.2-plan.md`](docs/v0.2-plan.md).

## License

MIT.

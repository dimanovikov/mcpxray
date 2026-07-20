# mcpscore

**Static linter + 0–100 scorecard for MCP servers.** `mcpscore` scans an MCP server's source (or a captured `tools/list` manifest) and flags tool poisoning, leaked secrets, schema drift, over-permissive tools and more — locally, deterministically, in CI. One score, one badge.

> MCP is the fastest-growing dev protocol since GraphQL (97M SDK downloads/month), but 7%+ of servers ship with vulnerabilities and no one lints them. `mcpscore` is the missing `npm audit` + OpenSSF Scorecard for MCP — static, local-first, OSS.

## Status

🚧 **v0.0.0 — scaffolding.** Not usable yet. v0.1 will ship the Python static extractor + rules MCP101–MCP109 + CLI (`scan`/`score`/`badge`).

## Install (planned)

```bash
uv tool install mcpscore
# or: pip install mcpscore
```

## Commands (planned)

| Command | Purpose |
| --- | --- |
| `mcpscore scan [PATH] [--manifest FILE] [-f plain\|json\|github\|sarif] [--check]` | Lint a server; exit 1 on any ERROR. |
| `mcpscore score [PATH] [--fail-under N]` | Print the 0–100 score; exit 1 under threshold. |
| `mcpscore badge --score N -o badge.svg` | Render a score badge (SVG). |
| `mcpscore version` | Print the version. |

## Why

- **Static, not runtime.** No need to start the server — parse `@mcp.tool` definitions straight from source (or a `tools/list` dump). Deterministic and CI-safe.
- **MCP-semantic.** Knows about tool poisoning, schema drift, JSON-Schema compatibility — things generic SAST and OpenSSF Scorecard can't see.
- **Plugin-friendly.** Add a rule or an extractor in one file. See `CONTRIBUTING.md` (coming soon).

## License

MIT.

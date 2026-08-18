# Progress log

Living log of milestones and current state. Newest first.

## 2026-08-18 — v1.0.0 released, repo public 🚀

**Shipped today:**

- **Rebrand `mcpscore` → `mcpxray`** (`b6b74c4`) — the PyPI name `mcpscore` belongs to an active competitor (v1.6.0, own domain) whose package also installs a `mcpscore` command and import package, so coexistence was impossible. Renamed across dist/import/CLI/docs/repo URL.
- **PyPI dist renamed to `mcpxray-cli`** (`4cacdba`) — PyPI blocks the name `mcpxray` as confusable with the existing [`mcp-xray`](https://pypi.org/project/mcp-xray/) package: PyPI's name check strips `. _ -` and maps `i/l → 1`, `o → 0`, so every spelling of `mcpxray` collides exactly. Verified against PyPI's `ultranormalize_name` source and a sweep of all ~872k PyPI names. The **CLI command, import package, entry points and repo name all stay `mcpxray`** — only the distribution name changed. PEP 541 dispute was ruled out (the blocker is a live project, exact collision).
- **v1.0.0** (`74fe33a`, tag `v1.0.0`) — version bump, README/AGENTS Status + Rules tables brought in line with what actually ships (all rules MCP101–109, 224 tests), and a real bug fixed: `__version__` still read package metadata under the old dist name, so `mcpxray version` printed `0.0.0` from the installed wheel.
- **Published to PyPI**: <https://pypi.org/project/mcpxray-cli/> — wheel + sdist + Sigstore attestations, via trusted publishing (no token in the repo). First attempt failed with `invalid-publisher` because the pending-publisher form on PyPI hadn't actually been saved; after re-submitting it, `gh run rerun --failed` went green.
- **Repo flipped public**: <https://github.com/cloudroad-io/mcpxray> (verified anonymously reachable).

**State:** 224 tests green · ruff clean · CI green (py3.10–3.12 × ubuntu/windows) · install verified from real PyPI in a clean venv (`pip install mcpxray-cli` → `mcpxray version` → `1.0.0`; `mcpxray check` on the clean fixture → 100/100, exit 0).

**Maintainer notes:**

- The PyPI distribution is `mcpxray-cli`; the command, package and repo are `mcpxray`. `uvx mcpxray-cli …` and `pip install mcpxray-cli` both work.
- `pyproject.toml` must keep `module-name = "mcpxray"` under `[tool.uv.build-backend]` — `uv_build` derives `mcpxray_cli` from the dist name otherwise, and the build breaks.
- Trusted-publisher record on PyPI: owner `cloudroad-io`, repo `mcpxray`, workflow `release.yml`, environment `pypi`. The `pypi` GitHub environment exists (created via API, no protection rules yet).

**Next (pick up here):**

1. Announcement: Show HN, r/MCP, r/LocalLLaMA, X/Mastodon; PRs to awesome-mcp-servers / awesome-model-context-protocol.
2. Registry submissions: Glama, Smithery, PulseMCP.
3. Deferred features needing external services: hosted badge API, leaderboard.
4. v1.0.x maintenance: incoming issues, rule tuning, false-positive reports.

## Earlier

- **v0.2 (pre-release, in-repo)** — TypeScript static extractor (bracket-matching span scanner, Zod → JSON Schema), rules MCP105 (schema/impl drift) + MCP109 (transport auth/TLS), opt-in runtime `tools/list` capture (`--runtime --command`), friendly `check` verdict (🟢/🟡/🔴/⚪), GitHub-URL clone scoped to the server entry point, `card` report, `--fix`/`--diff` for MCP108, pre-commit hook, frozen plugin API (`__all__` + SemVer policy). Plan: [`docs/v0.2-plan.md`](v0.2-plan.md).
- **v0.1.0** — Python static extractor + manifest extractor, rules MCP101/102/103/104/106/107/108, `scan`/`score`/`badge`/`version`, plain/json/github/sarif reports, 0–100 score with error cap, SVG badge, plugin API.

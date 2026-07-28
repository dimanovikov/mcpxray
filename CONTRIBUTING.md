# Contributing to mcpscore

Thanks for helping make MCP servers safer. This guide covers the dev loop and the two ways most contributors extend `mcpscore`: **adding a rule** and **adding an extractor**.

## Development setup

```bash
git clone https://github.com/cloudroad-io/mcpscore
cd mcpscore
uv sync
uv run pre-commit install     # optional: ruff on every commit
uv run pytest                 # 70 tests
```

Before opening a PR:

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

CI runs the same on Python 3.10 / 3.11 / 3.12 / 3.13.

## Project layout

```
src/mcpscore/
  ir.py                 # McpServer, Tool, Diagnostic, severities, risk tiers
  extract/              # base.py (API) + python_static.py + manifest.py
  rules/                # base.py (API) + builtin/{descriptions,source,schema,supply}.py
  score.py  badge.py    # 0-100 score + SVG badge
  report/               # plain / json / github / sarif
tests/
  unit/  cli/  fixtures/servers/   # clean, poisoned, leaky, bare, unpinned, weak_schema
```

## Add a rule

Rules live in `rules/builtin/` (or your own module that you import so the decorator fires). Subclass `Rule`, decorate with `@register_rule`, implement `check`:

```python
# src/mcpscore/rules/builtin/my_rule.py
from collections.abc import Iterable

from mcpscore.ir import SEVERITY_WARNING, Diagnostic, McpServer
from mcpscore.rules.base import Rule, register_rule


@register_rule
class MCP200NoTools(Rule):
    id = "MCP200"
    severity = SEVERITY_WARNING

    def applies(self, doc: McpServer) -> bool:
        return doc.source_mode == "static"

    def check(self, doc: McpServer) -> Iterable[Diagnostic]:
        if not doc.tools:
            yield Diagnostic(
                rule_id=self.id,
                severity=self.severity,
                message="server exposes no tools",
            )
```

Then make sure the module is imported so registration runs — add it to `rules/builtin/__init__.py` (builtins) or declare an entry-point (external packages):

```toml
[project.entry-points."mcpscore.rules"]
my-rule = "my_pkg.rules:MCP200NoTools"
```

Add a fixture under `tests/fixtures/servers/` and a test in `tests/unit/test_rules.py` mirroring the existing ones. Pick the lowest free `MCP2xx` id for a non-builtin rule.

## Add an extractor

Same shape — subclass `Extractor`, decorate with `@register_extractor`:

```python
# my_pkg/extractors.py
from pathlib import Path

from mcpscore.extract.base import Extractor, register_extractor
from mcpscore.ir import McpServer, ServerMeta, Tool


@register_extractor
class MyLangExtractor(Extractor):
    language = "mylang"

    def applies_to(self, path: Path) -> bool:
        return path.is_dir() and any(path.rglob("*.mylang"))

    def extract(self, path: Path) -> McpServer:
        server = McpServer(meta=ServerMeta(name=path.name, language="mylang", path=str(path)))
        # ... parse *.mylang into Tool(...) entries ...
        return server
```

`extractor_for(path)` returns the first registered extractor whose `applies_to` is True, so make yours specific enough not to shadow the Python/manifest extractors.

## Scoring

New rules participate in scoring automatically — each `error` finding deducts 20 and caps the score at 60, each `warning` deducts 6, each `info` deducts 1. Set `severity` and (for future weighting) `risk` on the rule; you don't touch `score.py`.

## Conventions

- Python ≥ 3.10. Type hints required on public APIs.
- ruff (`E/F/I/UP/B/SIM`, line 100) is the only linter; `ruff format` is the only formatter.
- Tests: one fixture per rule/behavior, assert on rule ids and exit codes, not on prose.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`).

## Plugin API stability

`mcpscore` follows [SemVer](https://semver.org/) from **v1.0** on. The plugin surface — what external rule/extractor packages may import and rely on — is **frozen** and is defined by each module's `__all__`:

| Import path | Stable names |
| --- | --- |
| `mcpscore.ir` | `McpServer`, `ServerMeta`, `Tool`, `Diagnostic`, `Resource`, `Prompt`; severities (`SEVERITY_ERROR`/`_WARNING`/`_INFO`); risk tiers (`RISK_CRITICAL`/`_HIGH`/`_MEDIUM`/`_LOW`); `SOURCE_STATIC`/`_MANIFEST`/`_RUNTIME`; `ERROR_SCORE_CAP`; `severity_rank` |
| `mcpscore.rules.base` | `Rule` (its `id`/`severity`/`risk` attributes and `applies`/`check` methods), `register_rule`, `rules`, `run_all` |
| `mcpscore.extract.base` | `Extractor` (its `language` attribute and `applies_to`/`extract` methods), `register_extractor`, `extractors`, `extractor_for` |
| `mcpscore` (top level) | `__version__` only |

Contract:

- **Stable** (listed in `__all__`, no leading underscore): backward-compatible changes only within a major version. Removing a name, renaming it, or changing a signature/return type/field meaning is a **breaking change** → requires a major-version bump (`v2.0.0`) and a migration note.
- **Internal** (not in `__all__`, or prefixed `_`): the registry containers (`_RULES`, `_EXTRACTORS`), `RISK_WEIGHT`, `_SEVERITY_RANK`, the score internals, and every module not listed above (`cli`, `fix`, `score`, `runtime`, `report/*`, `extract/python_static`, `extract/typescript_static`, `extract/manifest`, `rules/builtin/*`). These can change in any release — **don't import them from external packages**.
- **Experimental** (present in `ir.py`, deliberately *not* in `__all__`): the auto-fix types `Fix` / `TextEdit` and `Diagnostic.fix`. Only MCP108 emits fixes today; the shape may change before it's promoted to the stable API (it'll graduate into `__all__` once a second rule uses it).
- New optional parameters/fields are additive (not breaking); new rule ids, severities, risk tiers, and `source_mode` values may be added in minor releases.
- Entry-point group names — `mcpscore.rules` and `mcpscore.extractors` — are part of the stable contract.

If you're about to change a stable name or signature, treat it as breaking and bump the major version (or add the new form alongside the old and deprecate the old first).

## Releasing

Maintainers only. Publishing is **tokenless** via [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — the `.github/workflows/release.yml` workflow builds an sdist + wheel with `uv build` and uploads to PyPI whenever a `vX.Y.Z` tag is pushed. No API token is stored in the repo.

To cut a release:

1. Bump `version` in `pyproject.toml`, update the README/CHANGELOG if any, commit on `main`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z` — the Release workflow runs (build → publish to the `pypi` environment).
3. Watch the workflow; on success the version is live on PyPI within a minute.

**One-time PyPI-side setup** (only needed before the *first* release — needs the maintainer's PyPI account, so it's not automated):

- On PyPI, register the `mcpscore` project (the first `v` tag will fail until this exists — PyPI rejects uploads to unknown projects).
- Under the project → *Publishing*, add a trusted publisher: **PyPI repository** `cloudroad-io/mcpscore`, **workflow filename** `release.yml`, **environment** `pypi`.
- In the GitHub repo, create an environment named `pypi` (Settings → Environments) so the workflow's `environment: pypi` resolves.

Optional hardening for later: add required reviewers or a deployment branch rule to the `pypi` environment; set up test-PyPI as a staging publisher first if you want a dry run.

## License

By contributing you agree your changes are licensed MIT, like the rest of `mcpscore`.

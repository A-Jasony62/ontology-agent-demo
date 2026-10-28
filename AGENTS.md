# AGENTS.md

Chinese-language ontology × agent demo: a domain-agnostic OWL 2 RL engine (`reasoner/`) + the `agent_task` domain plugin (`domains/`) + FastAPI (`api/`) + a separate MCP server (`mcp/`) + a React/Vite workbench (`frontend/app/`). Keep docs, comments, and user-facing strings in Chinese; match the existing style.

## Layout boundaries

- `reasoner/` must stay free of domain vocabulary (`Agent`, `Task`, `can_execute`). Domain rules, config, and MCP tools live in `domains/<name>/`; the plugin contract is `NAME`, `DESCRIPTION`, `create_adapter(engine, config)`, plus `ONTO_FILE` and `mcp.register_tools` for MCP domains. `domains/registry.py` discovers packages at runtime.
- `api/main.py` hardcodes `agent_task`. A new domain is reachable through `mcp/mcp_server.py --domain <name>` without code changes, but not through the REST API unless `api/main.py` is updated.
- Domain display names come from `rdfs:label` in the OWL file; do not duplicate them in `config.json`. Property names default to ontology short names (`config.json` only overrides them).
- `frontend/app/` is the real UI. `frontend/app/dist/` is gitignored and built by `npm run build` or the Docker frontend stage; it is not committed.
- `pipeline/gates.json` + `pipeline/shapes/<domain>.ttl` configure G1–G4 gates; `docs/MODELING_PIPELINE.md` is the authoritative gate spec, `reasoner/pipeline_gate.py` the implementation.

## Commands

```bash
make setup                 # create .venv and install requirements
make test                  # .venv/bin/python -m pytest tests/ -q
make run                   # API + workbench at http://127.0.0.1:8000
make mcp                   # MCP HTTP server at http://127.0.0.1:9000/mcp
bash scripts/start.sh      # venv + deps + API + open browser
```

- The Makefile hardcodes `.venv/bin/*`; run commands from the repo root. Backend tests need no running server or network.
- Single backend test: `.venv/bin/python -m pytest tests/test_reasoning.py -k r1 -q`.
- Frontend (from `frontend/app/`): `npm ci`, `npm run typecheck`, `npm run test`, `npm run build` (build includes typecheck). Single vitest file: `npx vitest run src/store/editorStore.test.ts`.
- Current suites: 178 backend tests, 68 frontend tests. Counts in README/CONTRIBUTING are stale; trust `pytest`/`vitest` output.
- No backend linter/formatter/typechecker is configured; do not invent one. CI is pytest on Python 3.10–3.12 plus a Node 20 frontend job. The local `.venv` is Python 3.14; `make docs` cannot install mkdocs there (no watchdog wheel), so doc builds are verified in CI on 3.12.
- `scripts/query.py` is HTTP-first with `--local` fallback; `scripts/query.py` and `scripts/ontologyctl.py` read `DOUBAO_API_BASE` (default `http://127.0.0.1:8000`).

## Gotchas

- `GET /` only serves the workbench after `frontend/app/dist` exists; otherwise it returns a build-instruction JSON. For development run Vite (`npm run dev`, port 5173), which proxies `/api` to port 8000.
- The MCP server embeds its own engine and does not need the API. `make mcp` is streamable HTTP; use `--transport stdio` for local MCP clients.
- Loading or saving a new ontology switches the API to generic mode: domain endpoints (`/api/reason`, `/api/classify`, `/api/ontology`, etc.) return 400, while generic query/materialized/source/export endpoints still work. `POST /api/ontology/reload` always rebuilds from the default core `.owl`, so it also exits generic mode.
- `reasoner.engine.get_engine()` is a process-wide singleton keyed by `(onto_path, extensions_dir)`; passing a different path replaces the shared engine. `api/main.py` holds mutable module globals `ENGINE`/`ADAPTER` and also reassigns `reasoner.engine._engine`; reference `api.main.ENGINE` dynamically instead of `from api.main import ENGINE`, and rebind both when swapping the default ontology.
- `mcp/` shadows the PyPI `mcp` SDK package. Sibling modules (`policy.py`, `tool_guard.py`) are loaded via `importlib` in `mcp/mcp_server.py`; do not switch that to `from mcp import policy`.
- Tests are not fully sandboxed: `test_reload.py` temporarily writes `.ttl` files into the real `domains/agent_task/extensions/`, `test_edit_model.py` overwrites and restores the real core `.owl`, and save tests write to gitignored `data/uploads/`. Do not run the suite in parallel with a server using `--watch`/`--reload`; if a run is interrupted, inspect `git status` and clean leftovers.
- `scripts/build_ontology.py` regenerates the core `agent_task_ontology.owl` from Python definitions. It does not merge API/Protégé edits back, so rerunning it discards those edits; `--clean` only leaves `extensions/` untouched.
- Persisted changes (`persist=true`) go to `domains/agent_task/extensions/*.ttl` (git-tracked domain assets) or `data/uploads/` (gitignored); `backups/` is gitignored. Keep new tests isolated with `tmp_path` like the existing ones.

## Conventions

- Conventional Commits with scopes (`engine`, `api`, `domains`, `frontend`, `mcp`, `scripts`, `docs`, `ci`), Chinese subjects.
- User-visible changes must be recorded under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog); internal refactors and CI/doc wording do not need entries. See `CONTRIBUTING.md` for release steps.
- The MkDocs nav in `mkdocs.yml` is explicit. Add new guide/manual pages there; `docs/guide/` is the site root and `docs/manual/` the user manual (sibling of `docs/guide/`). Root `docs/*.md` files are design/review documents, not published guide pages.

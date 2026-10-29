# AGENTS.md

Chinese-language ontology × agent demo: a domain-agnostic OWL 2 RL engine (`reasoner/`) + a domain plugin system (sample in `examples/agent_task/`, runtime packages under the configured root, default `domains/`) + FastAPI (`api/`) + a separate MCP server (`mcp/`) + a React/Vite workbench (`frontend/app/`). Keep docs, comments, and user-facing strings in Chinese; match the existing style.

## Layout boundaries

- `reasoner/` must stay free of domain vocabulary (`Agent`, `Task`, `can_execute`). Domain rules, config, and MCP tools live in a domain package; the plugin contract is `NAME`, `DESCRIPTION`, `create_adapter(engine, config)`, plus `ONTO_FILE`, optional `CAPABILITIES` / `SHAPES_FILE`, and `mcp.register_tools` for MCP domains. The contract is declared in `reasoner/protocol.py` (`AdapterProtocol`, 7 methods); missing methods make the endpoint return 501, not 500.
- Layout: `examples/<name>/` is what ships with the repo (a read-only template); `domains/` is the runtime root and is gitignored. `python scripts/ontologyctl.py domain install --from <path>` copies a package into the runtime root. Domain root and default domain come from `config/domain.json` (gitignored, copy from `config/domain.example.json`), overridable by `ONTOLOGY_DOMAINS_ROOT` / `ONTOLOGY_DOMAIN` or `--domains-root` / `--domain`.
- Neither `api/main.py` nor `mcp/mcp_server.py` names a domain any more: both resolve the default via config and load through `domains.registry`. `reasoner.engine.ONTO_PATH` is resolved at import time from the configured default domain (`default_onto_path()`: package `config.json` `onto_file` → unique `*.owl` → legacy path), so `reasoner` never imports a domain adapter (that would be circular).
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
- Current suites: 308 backend tests, 68 frontend tests. Counts in README/CONTRIBUTING are stale; trust `pytest`/`vitest` output.
- No backend linter/formatter/typechecker is configured; do not invent one. CI is pytest on Python 3.10–3.12 plus a Node 20 frontend job. The local `.venv` is Python 3.14; `make docs` cannot install mkdocs there (no watchdog wheel), so doc builds are verified in CI on 3.12.
- `scripts/query.py` is HTTP-first with `--local` fallback; `scripts/query.py` and `scripts/ontologyctl.py` read `DOUBAO_API_BASE` (default `http://127.0.0.1:8000`).

## Gotchas

- `GET /` only serves the workbench after `frontend/app/dist` exists; otherwise it returns a build-instruction JSON. For development run Vite (`npm run dev`, port 5173), which proxies `/api` to port 8000.
- The MCP server embeds its own engine and does not need the API. `make mcp` is streamable HTTP; use `--transport stdio` for local MCP clients.
- Loading or saving a new ontology switches the API to generic mode: domain endpoints (`/api/reason`, `/api/classify`, `/api/ontology`, etc.) return 400, while generic query/materialized/source/export endpoints still work. `POST /api/ontology/reload` always rebuilds from the default core `.owl`, so it also exits generic mode.
- **Domain runtime state lives in `domains/manager.py` (`DomainManager`)** — it is the single source of truth for "which domain is active" (name + engine + adapter + loaded_at). `api/main.py` keeps `ENGINE`/`ADAPTER` as a **per-request snapshot** of the manager: a middleware calls `_sync_runtime()` on every request, and the manager bumps `version` on each `activate` / `reload` / `use_engine`. Do not assign `api.main.ENGINE` expecting it to stick; go through `api.main.DOMAINS`. Tests that monkeypatch `M.ENGINE` still work because the sync is version-gated, not unconditional.
- **Hot switch semantics**: `POST /api/domains/reload` (L2, re-executes domain code) and `POST /api/domains/{name}/activate` (L3, another installed domain) both **build first, swap second** — any failure leaves the old domain serving and returns 400. `reasoner.engine._engine` is re-synced by the manager on every swap; forgetting this is the classic "domain changed but `/api/query` still answers the old graph" bug.
- **Generic mode is judged by engine identity**, not path equality: `DOMAINS.in_domain_mode()` is `_engine is _current.engine`. Loading an uploaded ontology replaces only the serving engine (`use_engine`), which is what makes domain endpoints return 400.
- MCP does **not** hot-switch domains: tool schemas are registered at startup, so switching a domain requires restarting the MCP server (`--domain` reads config). Do not try to swap the MCPServer instance in the event loop.
- `mcp/` shadows the PyPI `mcp` SDK package. Sibling modules (`policy.py`, `tool_guard.py`) are loaded via `importlib` in `mcp/mcp_server.py`; do not switch that to `from mcp import policy`.
- Tests: `tests/conftest.py` aliases the domain package as `domains.<name>` in-process (no on-disk shim), so `from domains.agent_task import ...` still resolves. If the runtime root has no domain installed, it copies `examples/agent_task` to a temp root and points `ONTOLOGY_DOMAINS_ROOT` there — a clean checkout can run the suite, and writes land in the copy. When a domain *is* installed, the suite still writes into the real runtime root (`test_reload.py` adds `.ttl` into `<root>/agent_task/extensions/`, `test_edit_model.py` overwrites and restores the core `.owl`), so do not run it in parallel with a server using `--watch`/`--reload`.
- Persistence is no longer git-tracked by default: `persist=true` writes go to `<runtime root>/agent_task/extensions/*.ttl`, and `domains/*/` is gitignored. Anything that must be versioned belongs in `examples/` (or a dedicated tracked location) — `scripts/ontologyctl.py` paths that `git add domains/...` need review before use.
- `scripts/build_ontology.py` regenerates the core `agent_task_ontology.owl` from Python definitions. It does not merge API/Protégé edits back, so rerunning it discards those edits; `--clean` only leaves `extensions/` untouched.
- `data/uploads/` (saved ontologies) and `backups/` are gitignored. Keep new tests isolated with `tmp_path` like the existing ones.

## Conventions

- Conventional Commits with scopes (`engine`, `api`, `domains`, `frontend`, `mcp`, `scripts`, `docs`, `ci`), Chinese subjects.
- User-visible changes must be recorded under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog); internal refactors and CI/doc wording do not need entries. See `CONTRIBUTING.md` for release steps.
- The MkDocs nav in `mkdocs.yml` is explicit. Add new guide/manual pages there; `docs/guide/` is the site root and `docs/manual/` the user manual (sibling of `docs/guide/`). Root `docs/*.md` files are design/review documents, not published guide pages.

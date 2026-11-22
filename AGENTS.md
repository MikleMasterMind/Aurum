# AGENTS.md

Aurum — self-hosted personal finance app. FastAPI + SQLAlchemy 2.0 (async) + Alembic backend, React 19 + TypeScript + Vite + Tailwind frontend, Playwright e2e. Docker Compose runs everything: Postgres (`db`), FastAPI (`backend`), nginx-served SPA (`web` at http://localhost:3000). Single-user by design — there is no login system (optional Basic Auth is enforced at nginx from env vars), so don't look for auth code in the backend.

API reference: `DOCS.md`; interactive Swagger at `/api/docs` on a running instance.

## Development workflow

Any code change goes through this process — nothing lands directly on `main`.
(Purely textual edits — docs and the like — may skip it.)

1. **Plan first, settle everything upfront.** Discuss the implementation plan with the user and get their approval before writing any code. Ask at the same time: merge into `main` or discard when done, and whether the user wants to sign off each commit after the review pass. Don't start until both are answered.
2. **Branch + worktree.** Create a separate branch and do the work in a dedicated worktree, not in the main checkout.
3. **Independent review before every commit.** Before each commit, run a reviewer subagent with fresh context (never the agent that made the changes) over the diff — it should check against the conventions in this file. Address its findings, then commit (wait for explicit user confirmation first, if opted in).
4. **Finish as agreed — don't ask again.** Execute the choice from step 1: either merge the branch into `main` with a regular merge commit (`--no-ff`) and then delete both the branch and the worktree, or discard — delete the worktree and the unmerged branch without merging.

## Commands

The Docker stack is the dev environment (works with no `.env` — compose has defaults):

```bash
docker compose up -d --build
```

Backend tests (integration tests over httpx) must run inside the running `backend` container — the only place with Postgres network access; dev deps aren't in the prod image:

```bash
docker compose exec backend pip install --user -r requirements-dev.txt  # once per container lifetime
docker compose exec backend python -m pytest -v                         # bare `pytest` isn't on PATH (unprivileged user)
docker compose exec backend python -m pytest tests/test_tags.py::test_x -v  # single test
```

Tests create/migrate/drop a dedicated `aurum_test` database per run — the real `aurum` DB is never touched. A `PytestCacheWarning` about `/app/.pytest_cache` is expected (read-only source tree).

Frontend (`cd frontend`):

```bash
npm run dev     # Vite on :5173, proxies /api to localhost:8000 (override with VITE_API_PROXY_TARGET)
npm run build   # tsc -b && vite build — the PR gate; type errors fail the build
npm run test    # vitest run (one-shot); single file: npx vitest run src/lib/format.test.ts
```

- `npm run lint` is only `tsc -b --noEmit` (typecheck — there is no linter).
- Unit tests are plain-function tests over `src/lib` and crypto components; they need jsdom because `lib/i18n.ts` reads localStorage at module load. `vitest.config.ts` is deliberately separate from `vite.config.ts`.

E2E (`cd e2e`): `./run.sh` brings up a fully isolated throwaway stack (compose project `aurum-e2e`, port 3100, DB `aurum_e2e`, own volume), waits for `/api/health`, runs Playwright, and always tears down with `down -v` — the real instance is never touched. Args pass through: `./run.sh tests/year-switcher.spec.ts`, `./run.sh --headed`. Runs with `workers: 1` against one shared DB — give each spec's seeded data a non-overlapping scope (e.g. distinct year/month), not a clean slate.

CI (`.github/workflows/ci.yml`): backend pytest against a real Postgres service + frontend `npm run build` and `npm run test`. E2e is not in CI.

## Conventions & gotchas

- **Schema changes need an Alembic migration.** Autogenerate must run in the container (`docker compose exec backend alembic revision --autogenerate -m "..."`) — Postgres isn't published to the host. The backend container is not bind-mounted, so copy the generated file out: `docker compose cp backend:/app/alembic/versions/<file>.py backend/alembic/versions/`. Always review it by hand — autogenerate isn't always right. Migrations apply automatically on container boot (`alembic upgrade head && uvicorn ...` in the Dockerfile CMD).
- **New models must be registered twice**: imported in `app/models/__init__.py` AND in `alembic/env.py` — otherwise autogenerate won't see them.
- **i18n is build-checked.** Every user-facing string goes in `frontend/src/lib/i18n.ts` in BOTH `ru` and `en`; `en` is typed `Record<keyof typeof ru, string>`, so a missing translation is a build error. Never hardcode UI text in a component.
- **All routes mount under `/api`**; FastAPI docs live at `/api/docs`/`/api/redoc`, not the defaults (nginx only proxies the `/api` prefix). New routers get wired in `app/main.py`.
- **Backend test style**: hit the API through the `client` fixture (httpx AsyncClient over the real ASGI app) like the frontend does — don't call services/models directly. `account_id` / `categories` fixtures give the default seeded data; every table is truncated and reseeded before each test. `pytest.ini` sets `asyncio_mode = auto` — async tests need no marker.
- **Startup seeding** (`app/db/seed.py`): the app lifespan seeds a default account, categories, and app settings; tests bypass lifespan and reseed per-test instead.
- **Versions are bumped in two places that must agree**: `backend/app/core/config.py` (`APP_VERSION`, the single source of truth, served via `GET /api/settings`) and `frontend/package.json`.
- **Mobile-first**: check UI changes at a narrow viewport before finishing.

## Standing user rules (from CLAUDE.md — still apply)

- Respond to the user in Russian.
- Never delete existing code comments — you may update them to stay accurate, but code must not end up without them.
- No sensitive data in code or the repo: no real passwords/logins, no real expense/income descriptions.
- Commit after important changes: short, simple message with a conventional prefix (`feat:`, `fix:`, `security:`, `build(deps):`), usually in Russian. Never mention AI models or session links in commit messages.
- Keep changes atomic — a change in one place must not break unrelated features.

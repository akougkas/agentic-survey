# Next session — ship M8, purge theater

Self-contained kickoff. Paste into a fresh Claude Code session. Two phases,
two commits. Phase 1 (purge) lands first so M8 builds on a clean runtime.

## Required reading

1. `.claude/CLAUDE.md` — runtime invariants. Read §Invariants and §Architecture.
2. `docs/MIRA-ROADMAP.md` — M1–M7.5 history, §"Gotchas discovered during
   M1 smoke" (1–14) and §"Gotchas discovered during M2" (15–24). Don't
   re-litigate solved problems.
3. This file. M8 details + purge punch list.
4. `~/.claude/plans/merry-snuggling-kahn.md` §M8 for the canonical UI plan.

## Shipped state

M1–M7.5 all in `git log`. Latest commits:

- `fa3fd5a` — migrations collapsed into a single `db/schema.surql` +
  `db/schema.py` CLI. Apply with `uv run python -m agentic_survey.db.schema`.
  Pre-1.0: no migrations. Schema changes = drop DB, re-apply.
- `3f177cd` — M7.5 SurrealRepository integration tests (18 against live
  container). Uncovered and fixed a `retrieval_audit_id` record-wrap bug
  in `append_interview_turn`.
- `455d84b` — M7 persona + prompt rewrites; purged 350+ LOC of dead
  scaffolding.

Unit + integration: 182 tests green (164 unit + 18 integration, ~6s).
Live smoke: `SURVEY_ADMIN_PASSWORD=change-me infra/ops/smoke.sh` PASSes.

## Phase 1 — Theater purge

Deliver this as one commit. Subject: `purge: orphan tables, dead code, silent fallbacks`.

All findings below are verified; no speculation. File paths are absolute-ish
from repo root. When in doubt, raise instead of defaulting.

### 1a. Silent-fallback invariant violations (MUST raise)

CLAUDE.md: "Every LLM failure, Surreal query failure, or parse failure
raises; the route returns the error." These four swallow errors:

- [ ] `services/api/agentic_survey/agents/designer.py:143–145` —
  `_knowledge_snapshot` wraps the repo call in `except Exception: return []`.
  The comment even admits "Failure isolates: an exception here never
  breaks the designer." Remove the try/except; let it raise.
- [ ] `services/api/agentic_survey/engine/interview_loop.py:428–430` —
  identical pattern in the interviewer-side `_interview_knowledge_snapshot`.
  Same fix.
- [ ] `services/api/agentic_survey/services/retrieval.py:236–239` —
  `_safe_get_source` catches everything and returns `None`. Rename to
  `_get_source`, let it raise. Callers that were defending against `None`
  can stop.
- [ ] `services/api/agentic_survey/api/invites.py:158–159` —
  `except KeyError: pass` silently skips session pinning when the
  endpoint key is missing. Either raise (preferred) or at minimum emit a
  `logger.warning`. No bare pass.

### 1b. Orphan schema tables (MUST drop from `db/schema.surql`)

Verified: none of these tables are written to by any non-test Python.
Drop them from the schema file. If any enum value or Python type refers
to the dropped table, drop that too. Keep the `analyst` *role* — the
LLM plumbing uses it — but drop the *table*.

- [ ] `knowledge_blob`
- [ ] `theme_cluster`
- [ ] `part_of_cluster`
- [ ] `analyst_report`
- [ ] `saturation_snapshot` — the in-memory dataclass in
  `engine/saturation.py` stays (signals code uses it); only the table
  goes. If the signals path needs persistence later, re-add the table
  with whatever shape the caller actually wants.
- [ ] `llm_call_audit` — defined in schema but the callbacks in
  `llm/callbacks.py:120,137` only write to `logger`, never to Surreal.
  Drop the table. DB-backed LLM audit is a follow-up feature, file it as
  a ticket not a scar.

After the drops, re-run the integration suite; `test_schema_apply.py`'s
`EXPECTED_TABLES` set must be updated in the same commit. The drift
guard (`test_schema_manifest_matches_expected_tables`) keeps the two in sync.

### 1c. Dead modules (MUST delete)

- [ ] `services/api/agentic_survey/agents/analyst.py` — defines
  `Analyst(BaseAgent)` with a system-prompt docstring. Zero imports. The
  `analyst` *role* (LLM catalog, models.yaml, client pool) is live and
  stays; the agent *class* never ran. Delete the file.
- [ ] Do **NOT** delete `tools/freshness.py`. It's the worker CLI entry
  point (`python -m agentic_survey.tools.freshness`) used by both
  `infra/docker-compose.local.yml:57` and `citadl/deploy/coolify/docker-compose.yml:62`.
  The recon-style check "imported by no Python module" misses CLI entry
  points.

### 1d. Dead config

- [ ] `services/api/agentic_survey/config.py` — delete the `rag_autosync:
  bool = False` field. Zero reads anywhere in non-config Python. The
  existing comment ("scaffold for a follow-up milestone") is the tell.
- [ ] `services/api/agentic_survey/services/ingestion/pipeline.py:225,233,236,260`
  — replace `getattr(settings, "ingest_xxx", default)` with direct
  `settings.ingest_xxx`. The fields exist on `Settings` already; the
  `getattr`-with-default is the pattern you use when you're not sure if
  a field is set, which invites silent typos.

### 1e. Doc hygiene

- [ ] `docs/KNOWLEDGE_GRAPH.md` — 25 lines, describes only orphan tables
  (`theme_cluster`, `part_of_cluster`, `analyst_report`). Once §1b lands,
  this doc is fiction. Either delete or rewrite to describe
  `concept` / `mentioned_with` / `contradicts` only.
- [ ] `docs/ARCHITECTURE.md` — 34 lines, last updated before the
  migrations collapse. Verify against the current tree; trim what no
  longer matches.

### 1f. Verification gate for Phase 1

```bash
cd services/api && uv run pytest -v         # all 182 still green
# Expect: fewer integration tests if you also tightened assertions
# around the orphan-table drops. Don't remove tests unless the thing
# under test was itself theater.

SURVEY_ADMIN_PASSWORD=change-me infra/ops/smoke.sh  # still PASS
```

Commit, then stop for scientist review. Do not fold into M8.

---

## Phase 2 — M8 UI affordances

Second commit. Subject: `M8: operator console — knowledge tab + live graph view`.

Only new runtime dep: `d3-force`. No chart libs, no state libs. Tailwind
classes only; no inline styles for anything load-bearing. Participants
never see any of this — everything lives under `/admin/`. Graph view
returns 403 on participant sessions.

### 2a. Knowledge tab — `/admin/campaigns/[id]`

Modify `apps/web/src/routes/admin/campaigns/[id]/+page.svelte`. Add a
"Knowledge" tab (or section; operator's call) with three panels:

1. **Web search.** Input + "Search" button. Calls the existing M3
   endpoint `POST /api/admin/campaigns/{id}/knowledge/search`. Render
   candidate cards with approve/reject buttons wired to
   `POST .../knowledge/{source_id}/approve` and `.../reject`. Render
   `rationale` if present.
2. **Ingestion queue.** Live-ish view of `knowledge_source` rows in
   states `queued | fetching | extracting | chunking | embedding`.
   Short-poll `GET /api/admin/campaigns/{id}/knowledge` every 3s while
   the tab is focused. SSE upgrade is a follow-up. Show `error_detail`
   when status is `failed` (gotcha #23: `error_detail` is preserved
   across intermediate bumps).
3. **Mira-proposed queries inbox.** Rows where `kind="searxng_suggestion"`
   and `source="brain_b_designer"`, pending approval. Approve/reject
   with the same M3 endpoints.

### 2b. Graph view — `/admin/campaigns/[id]/graph`

New route: `apps/web/src/routes/admin/campaigns/[id]/graph/+page.svelte`.

Force-directed graph via `d3-force` + SVG. Subscribes to
`/api/campaigns/{id}/stream` and handles `graph_delta` events emitted by
`engine/interview_loop.py::InterviewEvent(name="graph_delta", …)`.
Animate new nodes and edges as they arrive; distinguish
`mentioned_with` (neutral) from `contradicts` (red).

Initial state: fetch current neighborhood via a new
`GET /api/admin/campaigns/{id}/graph` endpoint returning
`{nodes, edges}` shaped after `list_graph_edges_for_campaign`. Build
that endpoint in `api/admin.py` if it doesn't exist.

### 2c. Type definitions

`apps/web/src/lib/types.ts` — add:

- `WebSearchResult`
- `KnowledgeSourceTimeline`
- `GraphDelta`

Mirror the backend Pydantic shapes exactly. Do not invent fields. If
a field on the backend is optional, keep it optional in TypeScript.

### 2d. Tests

- [ ] `apps/web/tests/admin-knowledge.spec.ts` — Playwright. Golden
  path: search via SearXNG → see candidates → approve one → ingestion
  queue shows the new source. Edge cases: empty search result,
  approve without admin auth (expect 401 redirect).
- [ ] No unit tests for the Svelte components themselves unless you
  find a real bug worth pinning. Playwright is the contract.

### 2e. Verification gate for Phase 2

```bash
cd services/api && uv run pytest -v          # 182+ still green
cd apps/web && npm run verify:e2e            # Playwright green
# Manual: open /admin/campaigns/{id}/graph while a participant runs
# an interview; confirm graph_delta events animate as edges land.
```

Commit, end.

---

## Invariants (do not break)

Copied from CLAUDE.md for convenience; the file is source of truth.

- **No silent errors.** Every LLM, Surreal, or parse failure raises.
  The route returns the error. No fabricated outlines, validations, or
  graph deltas.
- **SurrealDB is truth.** Post-schema, persistent state lives there.
  `InMemoryRepository` is for tests.
- **Runtime stays generic.** Product identity, campaign seeds, branding
  live in bundles, never in `services/api`.
- **Reasoning is an explicit catalog toggle.** No hidden thinking budgets.
- **`"Discuss this more."` is always the last chip.**
- **No turn ceilings.** Close authority is `BrainBIntent.should_close`
  OR participant stop OR scientist override.
- **No commits without user approval.**

## Smoke protocol

Between phases, run in this order:

```bash
# 1. SurrealDB up + schema current
docker compose -f infra/docker-compose.local.yml up -d surrealdb
cd services/api && uv run python -m agentic_survey.db.schema && cd -

# 2. Backend with reload
(cd services/api && nohup uv run uvicorn agentic_survey.main:app \
  --host 127.0.0.1 --port 8100 --log-level info --reload \
  > /tmp/api-dev.log 2>&1 &)
sleep 6 && curl -sS http://localhost:8100/api/healthz

# 3. Tests
cd services/api && uv run pytest -v && cd -

# 4. Live end-to-end
SURVEY_ADMIN_PASSWORD=change-me infra/ops/smoke.sh
```

Pass criteria: step 3 green, step 4 prints `smoke: PASS`.

## Commit policy

User holds commit authority. One commit per phase.

- Phase 1: `purge: orphan tables, dead code, silent fallbacks`
- Phase 2: `M8: operator console — knowledge tab + live graph view`

No combining, no amending across phases. Between phases, show a
`superpowers:code-reviewer` summary and wait for "ship it" before
committing. Commit message style matches `455d84b`: terse subject,
body lists surfaces touched and verification results.

## Scope boundary

If something on the punch list turns out to need more work than a
purge commit can absorb — e.g., dropping `saturation_snapshot`
requires rewriting a signals contract, or `llm_call_audit` is actually
referenced by an unreached endpoint — stop, flag it, and ask. Don't
expand scope. Don't resurrect features. Pre-1.0: if it doesn't have a
caller today, it doesn't ship today.

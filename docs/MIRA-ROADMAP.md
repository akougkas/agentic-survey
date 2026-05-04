# Mira agentic toolset — roadmap and live handoff

This is the single source of truth for the multi-milestone work turning Mira into a real tool-using agent. A new Claude Code session should read this end-to-end before touching code.

## TL;DR for a fresh session

- **Plan source:** `~/.claude/plans/merry-snuggling-kahn.md` (identical content, older copy).
- **What's done:** M1 shipped (`d6daca8`, `9f5d2da`); M2 shipped (this commit). Tool-calling Brain B works live; the ingestion worker drains queued URL/PDF sources end-to-end with real 768-dim Nomic embeddings.
- **What's next:** M3 (web search: SearXNG primary, DDG fallback, scientist-gated). See `~/.claude/plans/merry-snuggling-kahn.md` §M3.
- **Locked decisions (user-approved):**
  - Scope: full agentic toolset (M1–M8).
  - Fetcher: tiered — `httpx + readability-lxml + pypdf` first, escalate to `crawl4ai` for JS-heavy pages.
  - Web search: SearXNG primary, `ddgs` (duckduckgo-search fork) fallback.
  - RAG folder: `./campaigns/{slug}/rag/` is export-only; SurrealDB stays source of truth.

## Kickoff prompt for a fresh session

Paste this into the new session:

```
Continue the Mira agentic toolset work. Read docs/MIRA-ROADMAP.md — it carries
M1 results, live-smoke learnings, and the M2-M8 plan. Start with M2 (ingestion
pipeline). Invariants and conventions are in .claude/CLAUDE.md. Before writing
code, re-read the "Gotchas discovered during M1 smoke" section so you don't
re-litigate solved problems.
```

---

## Status

### M1 — Tool-calling Brain B ✅ shipped

Commits:
- `d6daca8 M1: Tool-calling Brain B with shared orchestrator`
- `9f5d2da M1 smoke fixes: real tool-calling end-to-end against live models`

Delivered:
- `agents/tools/{__init__,registry,definitions}.py` — `MiraTool`, `ToolRegistry`, six tool factories.
- `agents/brain_b_loop.py` — shared `run_brain_b_with_tools` orchestrator with budget cap, parse retry, Discuss-this-more normalizer, observed-only `retrieval_used`/`retrieval_chunks`.
- `agents/brain_b_{designer,interviewer}.py` — thin adapters.
- `agents/designer.py` + `engine/interview_loop.py` — pass approved grounding snapshot through.
- `agents/prompts/{designer,interviewer}_brain_b.md` — tool-awareness note, score-range clarification.
- `tests/unit/test_brain_b_loop.py` — 10/10 green.

**Live smoke verified (CITADEL bundle, mini + dynamo):**
- Brain B issued real OpenAI `tool_calls`, dispatched through our registry.
- `search_knowledge` hit SurrealDB BM25, returned `kchunk-4761e273d7e7`, wrote `retrieval_audit` row.
- Terminal `BrainBIntent` carried `retrieval_used=true`, `retrieval_chunks=["kchunk-4761e273d7e7"]`, quoted the chunk verbatim.
- 32 seconds per turn with 2 tool calls. "Discuss this more." chip invariant holds.

### M2 — Ingestion pipeline ✅ shipped

Delivered:
- `services/ingestion/{__init__,pipeline,embed}.py` — `process_source(source_id, repository, router)` linear state machine (`queued → fetching → extracting → chunking → embedding → pending_approval`), `run_once` / `run_forever` worker loop.
- `services/ingestion/fetchers/{http,pdf,crawl4ai}.py` — tier-1 `httpx + readability-lxml` and `pypdf`; tier-2 `crawl4ai` lazy-imported and flag-gated.
- `services/knowledge_ingest.py` — `url`/`pdf` seeds create `status=queued` rows; `raw_text` seeds stay chunked synchronously (unchanged).
- `tools/freshness.py` — rewritten as the real worker CLI (`python -m agentic_survey.tools.freshness [--once]`).
- `api/knowledge.py` — `POST /admin/campaigns/{id}/knowledge/upload-url` enqueues URL (auto-detects `.pdf` suffix).
- `repository.py` + `db/surreal_repository.py` — `error_detail` on status updates, `list_knowledge_sources_by_status`, `list_knowledge_chunks_for_source`, `update_knowledge_chunk_embedding`.
- `tests/unit/test_{fetchers_http,fetchers_pdf,ingestion_pipeline}.py` — 16 new tests, 41/41 green.
- Deleted stubs: `tools/fetcher.py`, `llm/embeddings.py`.

**Live smoke verified (CITADEL bundle, Surreal mode, dynamo embeddings):**
- `POST .../knowledge/upload-url` with Wikipedia URL queued `ksrc-1f62c87bf9dc`.
- `python -m agentic_survey.tools.freshness --once` completed in 1.5s.
- Readability extracted 10,655 chars → 11 chunks @ ~3,100 chars each.
- Nomic Embed Text v2 MoE returned 768-dim embeddings (first chunk starts `-0.0393…`, clearly non-zero).
- Source status `pending_approval`, `retrieval_audit` unaffected (approval path untouched).

### M3 — Web search (scientist-gated)

SearXNG primary + DuckDuckGo fallback. Mira's `propose_search_queries` tool queues `searxng_suggestion` rows. Interview surface never calls web.

### M4 — Hybrid retrieval (BM25 + vector + RRF)

`search_knowledge(query, k, mode)` fuses BM25 and MTREE cosine KNN via Reciprocal Rank Fusion. Query embedding cached per session.

### M5 — Knowledge graph wiring

`engine/graph_builder.py` rewrite: validator concepts and relations land in `concept` rows + `mentioned_with` / `contradicts` edges. `get_graph_neighborhood` tool exposed to Brain B.

### M6 — Campaign RAG folder (export)

`services/rag_export/writer.py` syncs SurrealDB to `./campaigns/{slug}/rag/{sources.jsonl,chunks/,queries.jsonl,graph.json,README.md}` on demand.

### M7 — Prompts and persona polish

Shared `mira_persona.md` preamble. Full rewrite of the four Brain A/B prompts. Tool-aware, warm, evidence-led.

### M7.5 — SurrealRepository integration tests (next)

**Motivation.** The unit suite exercises `InMemoryRepository` in 17 of 17 test files; `SurrealRepository` has zero coverage. The CLAUDE.md invariant says "SurrealDB is truth; InMemoryRepository is for tests only" — so the tests today validate the non-truth path. Every Surreal bug we have hit (gotchas #15–18: hyphenated record ids, missing `array::slice`, `GROUP BY` aggregation quirks, embedding route) was caught in live smoke, not in CI.

**Scope.** A new `services/api/tests/integration/` tier that spins up the local `surrealdb` container (docker compose fixture) and exercises `SurrealRepository` directly against it. Happy-path coverage on the hot queries:

- `search_knowledge_chunks_bm25` + `search_knowledge_chunks_vector` + RRF fuse
- `merge_concept`, `record_mentioned_with`, `record_contradicts`, `list_concept_neighborhood`
- `update_knowledge_source_status` + `error_detail` preservation
- `update_knowledge_chunk_embedding` (768-dim write + readback)
- `append_interview_turn` + `get_retrieval_audit` round-trip
- Canonical schema applies cleanly on a cold container

**Why before M8.** Catching a Surreal regression costs one stalled interview today. It will cost a botched UI demo tomorrow.

**Estimated effort:** ~1 day. ~200 LOC of tests + a `conftest.py` fixture that boots/tears down the container via `docker compose`.

### M8 — UI affordances

Knowledge tab on `/admin/campaigns/[id]` (web search, ingestion queue, Mira-proposed queries). New `/admin/campaigns/[id]/graph` page with live force-directed view via `graph_delta` SSE.

Full details of each milestone, including files to create/modify and tests, are in the Architecture + Milestones sections below (copied from the approved plan).

---

## Gotchas discovered during M1 smoke

Any future milestone should know these so they don't re-litigate:

1. **LM Studio drops `tool_calls` when `response_format=json_schema` is on the same request.** Local Dynamo models via LM Studio return empty content + empty tool calls when both are set. Fix pattern now baked into `brain_b_loop.py`: send `tools` without `response_format` during tool-capable iterations; only apply `response_format` + `tool_choice="none"` on a terminal call when the model returns content that doesn't parse cleanly. If M2+ adds new tool surfaces (analyst, ingest), apply the same pattern.

2. **`response_format` without `tools` still works.** Single-call mode (no registry) can send both freely. Verified by `test_single_turn_no_tool_calls_returns_intent`.

3. **Model self-reports are not trustworthy.** Nemotron will happily put `"No chunks retrieved yet. Awaiting search_knowledge results."` into `retrieval_chunks` even when no tool call fires. Our orchestrator overrides these fields from the observed tool-call history. If M4 adds hybrid retrieval, keep this pattern: derived fields come from the call log, not the model.

4. **Scale drift in scores.** Brain B emits `axes_coverage[*].score` on a 0–5 scale instead of 0–1 unless the prompt screams "[0.0, 1.0] fractions". Both Brain B prompts now carry explicit wording. When M7 rewrites prompts, preserve this.

5. **LiteLLM router + LM Studio tool calling verified end-to-end.** Direct probe confirmed tool_calls flow through the router correctly. No need to special-case the backend in `llm/router.py`.

6. **`uvicorn --reload` required for iterative dev.** The default `make api-dev` already sets `--reload`, but the CITADEL demo process was started without it; changes to Python files weren't hot-loaded. Always start with `--reload`, or expect to restart manually.

7. **Logger warnings from `agentic_survey.*` modules appear in stderr.** Uvicorn doesn't filter them; they show up in captured stderr log files. That's how we diagnosed the retrieval path. If you see no warnings where you expect them, the code path didn't actually run.

8. **`api/campaigns.py::submit_designer_turn` was not passing `repository` to `run_designer_turn`.** Fixed in `9f5d2da`. If new milestones add similar call sites (e.g., an analyst runner), always forward the repository — the tool closures need it.

9. **SurrealDB BM25 uses `content @0@ $q`** where `0` is the search index position defined in `DEFINE INDEX ... FIELDS content SEARCH ANALYZER ascii_lower BM25`. Scores are negative (BM25 log-likelihood form). Lower score is worse in absolute value; ranking is still by `ORDER BY score DESC`.

10. **Unit tests use `asyncio.run` directly, not `pytest-asyncio`.** The repo's test deps don't include `pytest-asyncio`. Async code paths wrap in `asyncio.run(main())` inside a sync test function. See `test_brain_b_loop.py` for the pattern.

11. **Cosmetic chip leaks.** Brain B sometimes emits chips wrapped in square brackets (`"[Add 'Movement']"`) and sometimes only 3 chips instead of 4. The normalizer appends `"Discuss this more."` regardless, but the bracket wrapping reaches the UI. Prompt fix in M7.

12. **Brain B latency follows the reasoning budget.** Nemotron OMNI is configured with a 600K-token context window on dynamo, but Mira still caps completion output per role. Hidden reasoning uses `SURVEY_LLM_REASONING_BUDGET_TOKENS`; the request reserves `SURVEY_LLM_REASONING_FINAL_RESPONSE_TOKENS` beyond that so reasoning cannot consume the whole completion budget before the final JSON/probe is emitted. The `RetrievalCache` in `engine/retrieval_cache.py` mitigates repeat queries during interviews.

13. **Bundle paths.** The active bundle is `citadl/bundle` (via `SURVEY_PRODUCT_BUNDLE_DIR`). The `from-seed` endpoint expects `seed_slug`, not `slug` — field name landmine.

14. **Cookie jar dies on API reload.** Every `--reload` invalidates the admin session cookie. Re-login after any file save if you're scripting curl probes.

## Gotchas discovered during M2

15. **SurrealDB 2.6 record IDs need backticks in SQL when they contain hyphens.** `SELECT … WHERE id = knowledge_source:ksrc-1f62c87bf9dc` silently returns `[]` because the parser reads it as `knowledge_source:ksrc` minus literal `1f62c87bf9dc`. Always write `knowledge_source:\`ksrc-1f62c87bf9dc\``. The driver (RecordID) handles quoting itself; this only matters in the CLI / REPL.
16. **Surreal aggregation syntax.** `SELECT count() AS n FROM … GROUP BY status` fails without the grouped field in the projection. Write `SELECT status, count() AS n FROM … GROUP BY status` instead. For a single-row total, use `GROUP ALL`.
17. **Array slicing `embedding[0:5]` is not available in SurrealDB 2.6.** Index a single position (`embedding[0]`) for smoke tests; there is no `array::slice(start, end)` either. Dump to JSON and slice client-side if you must.
18. **`/api/system/context` exposes bundle identity but not runtime mode.** When debugging "is this process in `memory` or `surreal`?" you cannot tell from the HTTP surface — check `/proc/$PID/environ` or query SurrealDB directly. (Candidate follow-up: expose `repository` in the context response.)
19. **`embedding` model routes through the dynamo endpoint.** `litellm_config.yaml` pins `api_base: ${SURVEY_DYNAMO_ENDPOINT_URL}` for the `embeddings` model, so whichever LM Studio you point dynamo at must serve Nomic. If embeddings 404, check which model is loaded on dynamo, not the endpoint.
20. **`crawl4ai` is an optional extra.** M2 ships with `crawl4ai` lazy-imported from `services/ingestion/fetchers/crawl4ai.py`. It is listed in `[project.optional-dependencies].ingest`, NOT the main deps. Install with `uv pip install -e '.[ingest]'` when you need tier-2 escalation. The code raises a helpful `FetcherError` pointing at this install line if the package is missing and the feature flag is on.
21. **PDFs have no tier-2 escalation.** `fetch_pdf` failing raises `Tier1Insufficient` → pipeline marks source `failed`. Crawl4ai's magic mode is for HTML/JS pages, not binary PDFs; don't wire it up for PDFs.
22. **`KnowledgeChunk` Pydantic model doesn't carry the embedding vector.** Embeddings live only in Surreal (`knowledge_chunk.embedding`). `repository.update_knowledge_chunk_embedding(chunk_id, vec)` writes them; there is no `chunk.embedding` field on the Python model. For tests that care, the InMemory repo exposes `get_chunk_embedding(chunk_id)`.
23. **`update_knowledge_source_status` preserves `error_detail` by default; pass `error_detail=""` to clear.** Callers that omit the argument get preservation so a tier-1-insufficient note written during `fetching` survives through `extracting → chunking → embedding`. The pipeline explicitly clears at `pending_approval` (`error_detail=""`) and overwrites with a new string on `failed`. The UI can show the last-known note without losing it on intermediate retries.
24. **Worker idempotency is status-gated, not lock-based.** Two workers hitting the same source simultaneously would both see `status=queued` and race. M2 ships a single-worker assumption (one `tools.freshness` process). If we ever parallelize, wrap the first status transition in a conditional SurrealQL `WHERE status = 'queued'` to claim-or-skip.

---

## Smoke-test protocol (per milestone)

Between milestones, run this protocol to keep the live stack honest. All commands from repo root.

```bash
# 1. SurrealDB up + schema current
docker compose -f infra/docker-compose.local.yml up -d surrealdb
cd services/api && uv run python -m agentic_survey.db.schema && cd -

# 2. Backend in background with reload and log capture
(cd services/api && nohup uv run uvicorn agentic_survey.main:app \
  --host 127.0.0.1 --port 8100 --log-level info --reload \
  > /tmp/api-dev.log 2>&1 &)
sleep 6 && curl -sS http://localhost:8100/api/healthz

# 3. Unit suite
cd services/api && uv run pytest -v && cd -

# 4. Login + campaign + live turn
rm -f /tmp/cj
curl -sS -c /tmp/cj -X POST http://localhost:8100/api/admin/login \
     -H 'content-type: application/json' -d '{"password":"change-me"}'
CID=$(curl -sS -b /tmp/cj -X POST http://localhost:8100/api/campaigns/from-seed \
       -H 'content-type: application/json' -d '{"seed_slug":"domain-scientists"}' \
     | jq -r .id)
curl -sS -b /tmp/cj -X POST \
     "http://localhost:8100/api/admin/campaigns/$CID/knowledge/approve-all-seeds"
curl -sS -b /tmp/cj -X POST "http://localhost:8100/api/campaigns/$CID/designer/start"
curl -sS -b /tmp/cj -X POST "http://localhost:8100/api/campaigns/$CID/designer/turns" \
     -H 'content-type: application/json' \
     -d '{"content":"Call search_knowledge with query \"scientific data lifecycle phases\" and k=5. Report the exact chunk ids retrieved."}' \
     --max-time 240 | jq '.designer_session.turns[-1].brain_b_intent | {retrieval_used, retrieval_chunks}'

# 5. Confirm SurrealDB audit trail
docker exec -i infra-surrealdb-1 /surreal sql \
  --endpoint http://localhost:8000 --namespace agentic_survey --database prod \
  --username root --password root --pretty <<'SQL'
SELECT query, array::len(chunk_ids) AS hits, created_at
FROM retrieval_audit ORDER BY created_at DESC LIMIT 3;
SQL
```

**Pass criteria for any milestone:** step 3 green, step 4 returns `retrieval_used: true` with a real `chunk_id`, step 5 shows the new audit row. `infra/ops/smoke.sh` must also stay green.

---

## Architecture (from approved plan)

```
┌─ Brain B (tool-using, M1 ✅) ──────────────────────────┐
│  LiteLLM acompletion(tools=[...], tool_choice="auto")  │
│   → tool_calls → agents/tools/registry.py dispatches   │
│   → append tool-role messages → loop (cap 4 iters)     │
│   → final assistant message = BrainBIntent JSON        │
└────────────────────────────────────────────────────────┘
         │
         ├─ search_knowledge(query,k,mode)  → services/retrieval.py
         ├─ get_outline_state()             → closure
         ├─ list_grounding_sources()        → repository
         ├─ list_participant_faq()          → outline.participant_faq
         ├─ propose_outline_patch(patch)    → captured, applied post-turn
         ├─ propose_search_queries(qs)      → M3, design-time only
         ├─ get_graph_neighborhood(label,k) → M5
         └─ get_session_signals()           → interviewer only

┌─ Ingestion worker (M2) ────────────────────────────────┐
│  services/ingestion/pipeline.py                        │
│  queued → fetching → extracting → chunking → embedding │
│  → pending_approval                                    │
└────────────────────────────────────────────────────────┘
         │                    ↑
         ├─ fetchers/ ────────┘
         │   ├─ http.py      (httpx + readability-lxml)
         │   ├─ pdf.py       (pypdf + OCR hook stub)
         │   └─ crawl4ai.py  (escalation tier)
         └─ web_search/ (M3)
             ├─ searxng.py
             └─ ddg.py       (ddgs package)

┌─ Retrieval (M4, hybrid) ───────────────────────────────┐
│  BM25 (existing) + MTREE cosine KNN + RRF fusion       │
│  Query embedding via router.aembedding("embeddings")   │
└────────────────────────────────────────────────────────┘

┌─ Knowledge graph (M5) ─────────────────────────────────┐
│  engine/graph_builder.py writes into concept &         │
│  mentioned_with every participant turn, driven by      │
│  validator_result.extracted_{concepts,relations}.      │
└────────────────────────────────────────────────────────┘
```

---

## M2 smoke-test protocol (executable)

```bash
# Preconditions: SurrealDB up, schema applied, api-dev running in surreal mode.
rm -f /tmp/cj
curl -sS -c /tmp/cj -X POST http://localhost:8100/api/admin/login \
  -H 'content-type: application/json' -d '{"password":"change-me"}'
CID=$(curl -sS -b /tmp/cj -X POST http://localhost:8100/api/campaigns/from-seed \
  -H 'content-type: application/json' -d '{"seed_slug":"domain-scientists"}' | jq -r .id)
curl -sS -b /tmp/cj -X POST \
  "http://localhost:8100/api/admin/campaigns/$CID/knowledge/upload-url" \
  -H 'content-type: application/json' \
  -d '{"url":"https://en.wikipedia.org/wiki/Research_design","title":"Research design"}'

# Drain the queue once.
SURVEY_REPOSITORY=surreal SURVEY_LLM_ENABLED=true \
  uv run python -m agentic_survey.tools.freshness --once

# Verify status.
curl -sS -b /tmp/cj "http://localhost:8100/api/admin/campaigns/$CID/knowledge" \
  | jq '.by_status | keys'

# Verify embeddings were written.
docker exec -i infra-surrealdb-1 /surreal sql \
  --endpoint http://localhost:8000 --namespace agentic_survey --database prod \
  --username root --password root --pretty <<SQL
SELECT position, array::len(embedding) AS dim, embedding[0] AS first
FROM knowledge_chunk
WHERE source = knowledge_source:\`ksrc-...\` ORDER BY position LIMIT 2;
SQL
```

Pass criteria: status goes `queued → pending_approval` within one tick; `dim=768`; first value is a non-zero float.

---

## M2 plan (shipped — retained for provenance)

**Goal:** `knowledge_source.status=queued` rows march through `fetching → extracting → chunking → embedding → pending_approval` automatically. Scientists approve via the existing knowledge rail.

**New / modified files:**
- `services/api/agentic_survey/services/ingestion/__init__.py` (new)
- `services/api/agentic_survey/services/ingestion/pipeline.py` — `async def process_source(source_id, repository, router) -> None`. Idempotent state machine keyed by `knowledge_source.status`.
- `services/api/agentic_survey/services/ingestion/fetchers/http.py` — `httpx.AsyncClient` + `readability-lxml` → clean text.
- `services/api/agentic_survey/services/ingestion/fetchers/pdf.py` — `pypdf` + text normalization.
- `services/api/agentic_survey/services/ingestion/fetchers/crawl4ai.py` — lazy import; escalation tier only.
- `services/api/agentic_survey/services/ingestion/embed.py` — `async def embed_chunks(chunks, router) -> list[list[float]]` calling `router.aembedding(model="embeddings", input=[...])` in batches of 16.
- `services/api/agentic_survey/tools/fetcher.py` — delete (stub). Callers move to `services/ingestion/fetchers/*`.
- `services/api/agentic_survey/llm/embeddings.py` — delete (stub).
- `services/api/agentic_survey/tools/freshness.py` — rewrite: read `knowledge_source WHERE status=queued`, dispatch to `process_source`, sleep, loop. Respect `SURVEY_FRESHNESS_POLL_SECONDS` (default 30).
- `services/api/agentic_survey/services/knowledge_ingest.py` — already handles `raw_text`; extend to create `queued` rows for `url`/`pdf` seeds.
- `services/api/pyproject.toml` — add `crawl4ai>=0.4` (lazy-imported).

**Tier-1 → Tier-2 escalation rule:**
- Tier-1 (httpx + readability): fails if `content` < `SURVEY_INGEST_MIN_CHARS` (default 500), HTTP status ≥ 400, or readability throws.
- On failure, mark source `extracting` with `error_detail="tier1 insufficient"` and enqueue a tier-2 job. Tier-2 uses crawl4ai's `AsyncWebCrawler` with `magic=True, bypass_cache=False, js_code=[]`.

**Embedding:**
- On status `embedding`, iterate chunks in batches; call `aembedding`; write `knowledge_chunk.embedding` per row.
- If embedding fails, mark source `failed` with `error_detail` populated; no silent fallback (invariant).

**Tests:**
- `test_ingestion_pipeline.py`: state-machine transitions end-to-end against a fake repository + mock router.
- `test_fetchers_http.py`: readability extraction fixtures (static page + readability-fail case).
- `test_fetchers_pdf.py`: tiny fixture PDF → ≥N chars extracted.
- Smoke: real HTTP against `https://example.com` behind `SURVEY_INGEST_LIVE=true` flag.

**Verification once M2 lands:**
- `POST /api/admin/campaigns/{id}/knowledge/upload-url -d '{"url":"https://en.wikipedia.org/wiki/Research_design"}'` → `GET .../knowledge` shows the source walking statuses within ~20s.
- Embedding rows populate; `SELECT array::len(embedding) FROM knowledge_chunk LIMIT 1` returns 768.
- Smoke protocol above still passes; Brain B can now call `search_knowledge` on URL-sourced grounding.

---

## M3–M8 plan (reference)

Identical to `~/.claude/plans/merry-snuggling-kahn.md` §M3 through §M8. Not duplicated here to keep this doc scannable. Open that file when starting each milestone.

Per-milestone estimates: M2 ~3d, M3 ~1.5d, M4 ~2d, M5 ~2d, M6 ~1d, M7 ~1d, M8 ~2d.

Sequencing: **M2 → M3 → (M4 ∥ M5) → M6 → M7 → M8**.

---

## Cross-cutting

**Env vars to add (in `.env.example`) as milestones land:**
- M2: `SURVEY_FRESHNESS_POLL_SECONDS=30`, `SURVEY_INGEST_MIN_CHARS=500`, `SURVEY_INGEST_CRAWL4AI=true`.
- M3: `SURVEY_WEB_SEARCH_TOP_K=10`.
- M6: `SURVEY_RAG_AUTOSYNC=false`, `SURVEY_RAG_EXPORT_DIR=./campaigns`.

**Dependencies to add:**
- M2: `crawl4ai>=0.4` (lazy-imported in `services/ingestion/fetchers/crawl4ai.py`).
- M3: `ddgs>=9`.

**Schema:**
- Single canonical file at `db/schema.surql`; no migrations pre-1.0. Any change = drop DB, re-apply.

**Invariants preserved throughout:**
- No silent errors. Every fetcher, embedder, tool dispatch raises on failure; the route returns the error.
- SurrealDB is truth. RAG folder is export-only.
- No web calls mid-interview. Interviewer Brain-B registry excludes `propose_search_queries`.
- Reasoning is an explicit catalog toggle.
- `"Discuss this more."` last chip. Normalizer enforces it.
- No turn ceilings. Close authority = `BrainBIntent.should_close` OR participant stop OR scientist override.
- **No commits without user approval.** Ship when the scientist says ship.

---

## Key files (reference map)

Tool loop core (done in M1):
- `services/api/agentic_survey/agents/brain_b_loop.py`
- `services/api/agentic_survey/agents/tools/registry.py`
- `services/api/agentic_survey/agents/tools/definitions.py`

Surface adapters (done in M1):
- `services/api/agentic_survey/agents/brain_b_{designer,interviewer}.py`

Retrieval (extend in M4):
- `services/api/agentic_survey/services/retrieval.py`
- `services/api/agentic_survey/repository.py` (add `search_knowledge_chunks_vector`)
- `services/api/agentic_survey/db/surreal_repository.py`

Ingestion (new in M2):
- `services/api/agentic_survey/services/ingestion/{pipeline,embed}.py` + `fetchers/*.py`
- `services/api/agentic_survey/tools/freshness.py` (rewrite)

Web search (new in M3):
- `services/api/agentic_survey/services/web_search/{base,searxng,ddg,router}.py`

Graph (rewrite in M5):
- `services/api/agentic_survey/engine/graph_builder.py`
- `services/api/agentic_survey/engine/interview_loop.py` (wire call site)

RAG export (new in M6):
- `services/api/agentic_survey/services/rag_export/writer.py`
- `services/api/agentic_survey/api/admin.py` (endpoint)

Prompts (rewrite in M7):
- `services/api/agentic_survey/agents/prompts/mira_persona.md` (new)
- `services/api/agentic_survey/agents/prompts/{designer,interviewer}_brain_{a,b}.md`

UI (new in M8):
- `apps/web/src/routes/admin/campaigns/[id]/+page.svelte`
- `apps/web/src/routes/admin/campaigns/[id]/graph/+page.svelte` (new)

Functions to reuse across milestones:
- `tools/chunker.py::chunk_text`
- `engine/retrieval_cache.py::RetrievalCache`
- `llm/router.py::LiteLLMRouter.aembedding`
- `services/retrieval.py::build_search_knowledge` (keep the binding closure, swap the impl underneath)

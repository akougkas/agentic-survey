# Mira agentic toolset — roadmap and live handoff

This is the single source of truth for the multi-milestone work turning Mira into a real tool-using agent. A new Claude Code session should read this end-to-end before touching code.

## TL;DR for a fresh session

- **Plan source:** `~/.claude/plans/merry-snuggling-kahn.md` (identical content, older copy).
- **What's done:** M1 shipped in commits `d6daca8`, `9f5d2da`. Tool-calling Brain B works live against mini (Gemma-4) + dynamo (Nemotron) on localhost.
- **What's next:** M2 (ingestion pipeline with tiered fetchers + embeddings). See §M2 below.
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

### M2 — Ingestion pipeline (next)

Goal: `knowledge_source.status=queued` rows walk through `fetching → extracting → chunking → embedding → pending_approval` automatically. Scientist approves via existing knowledge rail. Nomic embeddings populate `knowledge_chunk.embedding`.

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

### M8 — UI affordances

Knowledge tab on `/admin/campaigns/[id]` (web search, ingestion queue, Mira-proposed queries). New `/admin/campaigns/[id]/graph` page with live force-directed view via `graph_delta` SSE.

Full details of each milestone, including files to create/modify and tests, are in the Architecture + Milestones sections below (copied from the approved plan).

---

## Gotchas discovered during M1 smoke

Any future milestone should know these so they don't re-litigate:

1. **LM Studio drops `tool_calls` when `response_format=json_schema` is on the same request.** Local models (tested: Nemotron Cascade 2 30B-A3B via LM Studio, direct probe) return empty content + empty tool_calls when both are set. Fix pattern now baked into `brain_b_loop.py`: send `tools` without `response_format` during tool-capable iterations; only apply `response_format` + `tool_choice="none"` on a terminal call when the model returns content that doesn't parse cleanly. If M2+ adds new tool surfaces (analyst, ingest), apply the same pattern.

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

12. **`~32s per Brain B turn with 2 tool calls.** Nemotron's reasoning trace dominates. Fine for design flow; the `RetrievalCache` in `engine/retrieval_cache.py` mitigates repeat queries during interviews. M4 vector retrieval will need query-embedding caching to stay under budget.

13. **Bundle paths.** The active bundle is `citadl/bundle` (via `SURVEY_PRODUCT_BUNDLE_DIR`). The `from-seed` endpoint expects `seed_slug`, not `slug` — field name landmine.

14. **Cookie jar dies on API reload.** Every `--reload` invalidates the admin session cookie. Re-login after any file save if you're scripting curl probes.

---

## Smoke-test protocol (per milestone)

Between milestones, run this protocol to keep the live stack honest. All commands from repo root.

```bash
# 1. SurrealDB up + schema current
docker compose -f infra/docker-compose.local.yml up -d surrealdb
cd services/api && uv run python -m agentic_survey.db.migrations.runner && cd -

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

## M2 plan (next milestone — detailed)

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

**Migrations:**
- M4: `db/migrations/0002_retrieval_audit_mode.surql` adds `mode` field.

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
- `integrations/research_agent.py::ResearchAgentHook` (bundle hook pattern)

# Agentic Survey — CITADEL demo + product rollout design

**Date:** 2026-04-19
**Status:** Approved by user. Under implementation.
**Scope:** Close runtime gaps for scope B (M3/M4/M5/M6/M8/M9), translate CITADEL Surveys A/B/C to campaign bundles, deploy to blade at `citadl.gnosis.run`, and lay groundwork for community productization. The Analyst/saturation pipeline (M7) and prompt polish (M10) are deferred to v1.1.
**Paired with:** `.planning/2026-04-19-execution-plan.md`, `.planning/2026-04-19-lifecycles.md`, `.planning/2026-04-19-mira-system-prompts-research.md`.

## 1. Context and goals

The agentic-survey runtime reached v0.1 with M1 (LiteLLM + SurrealDB DDL) and M2 (SurrealRepository) shipped. M3 (Designer dual-brain) and M5 (Interviewer dual-brain) are partially scaffolded; M4 (design-time ingestion), M6 (real streaming + chips + graph), M7 (Analyst), M8 (export/import), and M9 (deployment) are stub or missing. The next step is a real scientific study — the CITADEL surveys — run as the first genuine campaign, hosted on blade behind `citadl.gnosis.run`.

The user's framing requires that the product feel like a community-ready tool rather than a bespoke one-off. That means the runtime stays generic (product identity lives in bundles), the deployment path is reproducible, and the bundle authoring story is documented. This spec covers all of that except the gnosis.run landing page and full OSS polish (install.sh, CI, CONTRIBUTING, LICENSE), which are tracked as Phase D and deferred to a later approved session.

## 2. Scope

### 2.1 In scope

- **Phase A — Foundation:** env-var schema unification, bundle contract extensions (`seed_sources`, `research_agent_hook`), runtime decoupling verification, M3 close (domain types, readiness validator, Brain A/Brain B extraction, remove ≥4-turn gate).
- **Phase B — Grounded interview loop:** M5 extraction (brain_b_interviewer, retrieval_cache, session_policy demotion, interview_loop wiring), M4 backend (fetcher/extract/chunker/embeddings/worker + knowledge API + research_agent integration), M4 UI (KnowledgeRail + cards + upload modal), M6 streaming (real SSE/WS, GetUserInputChips, graph store, replace ChatPane + LiveGraphSigma mockups), SearXNG live.
- **Phase C — CITADEL instantiation + deploy:** three campaign bundles (Domain Scientists, Facility Operators, AI/ML Practitioners) derived from `citadl/seed/CITADEL-Surveys.md`, M8 export/import, `infra/` production compose + cloudflared route + Traefik labels + smoke script, Tailscale-based LLM routing to mini + dynamo, live deployment at `citadl.gnosis.run`.

### 2.2 Out of scope (deferred, not rejected)

- **Phase D — Community polish:** one-command `install.sh`, `docs/BUNDLE_AUTHORING.md` deep walkthrough, CONTRIBUTING.md, LICENSE, CI workflows, gnosis.run tools-collection landing page.
- **M7 Analyst:** HDBSCAN clustering, info-gain saturation curve, final report generation, SaturationChart frontend. Advisory-only saturation signal is deferred.
- **M10 Prompt polish:** Mira voice tuning on real transcripts. First-draft prompts ship with the demo.
- **Real Deep Research adapters:** `research_agent_hook` interface ships with `NullResearchAgent` only.
- **Cross-encoder retrieval reranking:** left as post-v1 per execution plan.
- **Reopen-after-archive flow:** not in any milestone.
- **Automated analyst dashboards / insights surfacing:** scientist does themes by hand on the exported archive until v1.1.

## 3. Architecture (delta from `.planning/`)

The lifecycles doc and designer-interview doc define the authoritative architecture. This spec references them rather than restating. Key deltas:

- **One campaign per CITADEL track.** Three independent campaigns (not one multi-track campaign). Rationale: saturation signals meaningfully per-track; Mira's persona calibration differs across audiences; analysis cells stay clean.
- **Frontend deployment = adapter-node, not nginx-static.** Rationale: the Svelte proxy is the only public surface; nginx-static would lose the `x-survey-public-base-url` forwarding and SSE proxying.
- **Env-var canonical convention = `SURVEY_SURREAL_*`** (audit-flagged mismatch with Coolify compose's `SURVEY_SURREALDB_*` resolved in Phase A).
- **Tailscale-only LLM routing.** Production API hits `mini.tail-<network>.ts.net:8080` and `dynamo.tail-<network>.ts.net:1234` via Tailscale. LAN IPs not used.

## 4. Phase A — Foundation

### 4.1 Env-var schema unification (A1 — completed)

Canonical: `SURVEY_SURREAL_*` matching `config.py`. Coolify compose rewritten. `.env.example` gains `SURVEY_PRODUCT_BUNDLE_DIR`, `SURVEY_EXPORT_DIR`, `SURVEY_EMBEDDING_MODEL`.

### 4.2 Bundle contract extensions (A2 — in progress)

`services/api/agentic_survey/bundles.py` parses `seed_sources` (per-campaign list of `{kind, url?, title, content_inline?, rationale}`) and `research_agent_hook` (per-product `{provider, config}`). `services/api/agentic_survey/integrations/research_agent.py` ships the `ResearchAgentHook` Protocol, three Pydantic payload types, and `NullResearchAgent` default. A `examples/product-bundles/demo-with-seeds/` smoke bundle exercises both fields.

### 4.3 Runtime decoupling verification (A3)

Grep `services/api/agentic_survey/**` for hardcoded product identity ("citadl", "CITADEL", branding strings). Any hits move to bundle config or default strings.

### 4.4 M3 close (A4 + A5 + A6)

- `domain/tools.py`: `GetUserInputOptions` Pydantic model. Validator enforces last option literally `"Discuss this more."`.
- `domain/outline.py`: `OutlineArtifactV2` with v2 fields (research_question, sampling_frame, exclusion_criteria, publication_intent, risk_register, grounding_sources_approved, readiness_rationale, decision_gate, suggested_search_queries).
- `agents/readiness.py`: pure function returning `list[str]` of unmet minimums; one English sentence each.
- Remove ≥4-turn gate in `agents/designer.py`.
- `BrainBIntent` Pydantic model (should_close, active_axis, axes_coverage, get_user_input, optional outline_patch).
- Extract `agents/brain_a.py` (shared Designer/Interviewer).
- Extract `agents/brain_b_designer.py` with tools (`search_knowledge` stub → live in Phase B, `get_outline_state`, `list_grounding_sources`, `propose_outline_patch`).
- Wire `api/campaigns.py` designer/turns endpoint to emit BrainBIntent-shaped events.
- Update `apps/web/src/lib/types.ts` with new types (rendering in Phase B).
- Attic legacy `designer.py` to `.attic/2026-04-19-m3-legacy-designer/`.

## 5. Phase B — Grounded interview loop

### 5.1 M5 extraction (Interviewer dual-brain)

Extract `agents/brain_b_interviewer.py` from the 784-LOC `interviewer.py`. Create `engine/retrieval_cache.py` (per-session, N=3 entries, TTL 10 min). Demote `engine/session_policy.py` to a signals helper (`SessionSignals`, no boolean close). Wire `engine/interview_loop.py` end-to-end. Add admin endpoint `GET /campaigns/{id}/sessions/{s}/turns/{t}/audit`. Attic legacy interviewer + validators.

### 5.2 M4 backend ingestion pipeline

Real `tools/fetcher.py` (httpx, timeout, size cap, robots.txt), new `tools/extract.py` (Readability-Lxml / pypdf / raw passthrough), upgraded `tools/chunker.py` (800/200 sentence-boundary snap), rewired `llm/embeddings.py` via LiteLLM `aembedding()`, new `worker/` package subscribed to `LIVE SELECT knowledge_source WHERE status='queued'`, new `api/knowledge.py` routes (upload/approve/reject/retire/retry + GET grouped cards), and the `seed_sources` hook from Phase A auto-creates `knowledge_source(kind="bundle_seed", status="pending_approval")` rows at campaign creation.

### 5.3 M4 UI rail

`KnowledgeRail.svelte`, `KnowledgeSourceCard.svelte`, `KnowledgeUploadModal.svelte`, `DeepResearchButton.svelte`. SSE `knowledge_source_changed` drives live status flips.

### 5.4 M6 streaming

`apps/web/src/lib/sse.ts` real EventSource wrapper with `Last-Event-ID` replay. `GetUserInputChips.svelte`. `stores/graph.ts`. Replace `ChatPane.svelte` mockup (real token stream + chips on `get_user_input`). Replace `LiveGraphSigma.svelte` CSS mockup (bound to `stores/graph.ts`). Replace `AnalysisGraphCytoscape.svelte` (bound to admin WebSocket). Backend: `api/ws/admin_graph.py`, `api/ws/validator_analyst.py`, `engine/streaming.py`, `api/turns.py` emitting full SSE taxonomy from `lifecycles.md` §2.7. Persist structured events only.

### 5.5 SearXNG live

`tools/searxng.py` real httpx client to `SURVEY_SEARXNG_URL`. Brain B's `propose_outline_patch` can emit `grounding_sources_proposed` with SearXNG results.

## 6. Phase C — CITADEL + M8 + blade deploy

### 6.1 CITADEL bundle translation

Three campaigns under `citadl/bundle/campaigns/`:

- `domain-scientists.yaml` — mirrors Survey A (research workflow pain points + AI readiness); persona tuned to peer-scientist tone; micro-form includes `discipline_picker`, `data_volume`, `computing_platforms`, plus evidence-of-belonging field.
- `facility-operators.yaml` — mirrors Survey B (production data infrastructure + ops gaps); persona tuned to peer-sysadmin tone; micro-form captures facility, tier, user base.
- `ml-practitioners.yaml` — mirrors Survey C (agentic AI capabilities + safety/deployment barriers); persona tuned to peer-researcher tone; micro-form captures ML specialization, scale, experience level.

Each YAML carries: research_question, sampling_frame (with exclusion_criteria), axes + probes derived from the seed's Tier 2/3 question families (not literal questionnaire items — Mira converses, not enumerates), persona_hints, consent_language, micro_form_schema, seed_sources (tier-intro prose from the seed doc as `kind: raw_text`).

`citadl/bundle/product.yaml` gets branding, the three campaign slugs, and `research_agent_hook: provider: null`.

### 6.2 M8 export / import

`engine/export.py` writes the directory tree from `lifecycles.md` §1.5 plus `manifest.json`. `--full` includes raw LLM prompts. `engine/import.py` validates manifest, creates rows with fresh IDs preserving relations. `cli.py` Typer entrypoint. Admin endpoints `POST /campaigns/{id}/export` and `GET /campaigns/{id}/export/{export_id}/download`. Admin UI "Export" button.

### 6.3 M9 blade deployment

- `infra/docker-compose.yml` — prod compose (api, worker, web, surrealdb, searxng) with Traefik labels.
- `infra/cloudflared/README.md` — instructions for adding the `citadl.gnosis.run` route to existing `blade-tunnel` (tunnel id per homelab inventory).
- `infra/traefik/labels.md` — Traefik labels reference.
- `infra/ops/smoke.sh` — full end-to-end smoke: create campaign → designer turns → ingest URL → launch → participant session → export → round-trip import. Must complete under 10 min.
- `services/api/Dockerfile` — hardened multi-stage.
- `apps/web/Dockerfile` — adapter-node image.
- `docs/DEPLOYMENT.md` — runbook: boot order, health checks, Traefik labels, cloudflared tunnel, rollback.

### 6.4 Tailscale LLM routing

`llm/litellm_config.yaml` endpoints use Tailscale hostnames for mini + dynamo. Verified via `llm_call_audit.endpoint_used`.

## 7. Success criteria (demo morning)

- `https://citadl.gnosis.run/` serves the SvelteKit app; TLS valid via cloudflared.
- Admin signs in with `SURVEY_ADMIN_PASSWORD`.
- Admin creates a campaign seeded from `citadl/bundle/campaigns/domain-scientists.yaml` (or Mira-driven from scratch if shown in the demo).
- Designer session shows real chip-ended turns with `GetUserInput`; outline revisions accrue with provenance; readiness validator rejects unready launches with unmet minimums surfaced.
- Knowledge rail accepts a PDF upload, shows status flips queued → pending_approval → approved with chunk count; `search_knowledge` by Brain B on a live turn shows in the admin "what Mira saw" drawer.
- Participant redeems an invite; interview turns stream token-by-token; chips render; graph updates live in Sigma.js; closing turn fires on `should_close=true`.
- Scientist triggers export; zip manifest + transcripts + knowledge + graph match DB counts; round-trip import on a fresh DB reproduces the campaign.

## 8. Risks and mitigations

- **Blade deploy hits unexpected Coolify/Traefik issue at 3am.** Mitigation: freeze at localhost-working and leave the deploy steps ready; demo falls back to `http://localhost:5270` shared via screen.
- **M6 streaming regression breaks participant flow.** Mitigation: keep the existing ChatPane as a fallback component; wire the new stream behind a `SURVEY_FRONTEND_STREAMING=beta` flag that defaults to on but can be flipped at deploy time if broken.
- **LiteLLM router endpoint flap.** Mitigation: the router already has fallback logic; audit endpoints are Tailscale so as long as Tailscale is up, mini + dynamo are reachable. If both fail, the pinned Brain A endpoint is lost → `session_paused` → demo can resume from the pause.
- **CITADEL bundle seed_sources have rich prose that may not chunk well.** Mitigation: chunker is content-agnostic; raw_text with content_inline lands as one chunk if short. Acceptable for demo.

## 9. Deferred to Phase D / v1.1

- gnosis.run tools-collection landing page (replacing Astro placeholder).
- `install.sh` one-command bootstrap.
- `docs/BUNDLE_AUTHORING.md` walkthrough tutorial.
- CONTRIBUTING.md, LICENSE (MIT or Apache-2.0 to be picked with user awake), `.github/workflows/` CI.
- M7 Analyst (HDBSCAN + saturation + final report + SaturationChart).
- M10 Mira prompt polish on real transcripts.
- Real Deep Research adapters.

## 10. Execution envelope

Work is dispatched as atomic prompts to the `as-claude` tmux session (Claude Code, bypass-permissions). Each prompt is ≤300 LOC diff, ≤15 min execution, ends with a verification command and a report-back. Phases are committed at their boundaries. The user committed to approving everything overnight; destructive ops and blade infrastructure restarts remain behind explicit morning approval per homelab AGENTS.md.

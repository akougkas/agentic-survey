# Agentic Survey

A reusable runtime for running rigorous qualitative interview campaigns with a multi-agent system. One scientist defines a topic, a Campaign Designer (Mira) pairs with them to shape a defensible study, and an Interviewer (also Mira) runs the live interviews in a conversational voice that feels like a coffee-break, not a form. A Validator scores every participant turn, an Analyst synthesizes themes across the corpus, and SurrealDB holds the whole thing as documents, vectors, and graphs.

This is not a chatbot. It is not Qualtrics with a wrapper. It is a single scientist's force-multiplier for qualitative research.

## Thesis

Qualitative research at IRB scale is expensive, slow, and hard to staff. Small-team research sacrifices rigor to move. The premise here is that a thoughtful multi-agent system, wrapped around good local LLMs, can close that gap. The system designs studies with methodological scrutiny, interviews participants with genuine curiosity, validates answers without contaminating them, and synthesizes findings without hallucinating. Every Mira turn ends with a structured `GetUserInput` chip set whose last option is always "Discuss this more." — the agentic survey way is structured-pool-backstage, conversational-flow-foreground.

## What ships

- A **Campaign Designer** that walks the scientist through five axes (research question, sampling frame, evidence standard, risk map, closure) and produces a durable `OutlineArtifact`.
- An **Interviewer** that runs live one-on-one interviews from the outline, handles digression and confusion and refusal, surfaces a proactive skip when a turn turns sensitive, and answers study-about questions from a curated FAQ.
- A **Validator** that reads each participant turn and emits `coverage_score`, `quality_score`, `follow_up_needed`, `extracted_concepts`, and `extracted_relations` with confidences.
- An **Analyst** scaffold wired for HDBSCAN-over-embeddings theme clustering and information-gain scoring (the full loop lands in a later milestone).
- A **SvelteKit operator shell** at `/admin/*` and a **participant shell** at `/invite/*` and `/chat/*`, proxied through a single port.

## The dual-brain Mira

Mira is two brains behind one voice.

- **Brain A (Chatter).** Qwen 3.5 Distilled on a llama.cpp endpoint. Session-pinned, warm prose, no tools. Its entire job is producing the visible reply and calling `GetUserInput`.
- **Brain B (Scientist).** Gemma 4 26B-A4B on the same endpoint, reasoning on by default. Stateless. Has tools: `search_knowledge`, `get_outline_state`, `list_grounding_sources`, `propose_outline_patch`. Brain B is the expert Brain A consults silently.

Two surfaces share this architecture: **Designer-Mira** (pair-programming with the scientist during campaign design) and **Interviewer-Mira** (conversing with a participant during a live session). Same dual-brain, different voices. Every participant turn triggers three LLM calls: Brain B plans intent, Brain A speaks, Validator scores.

## Reasoning framework

Each agent role has an explicit reasoning policy on its catalog entry: `off`, `on`, or `budget` (with `reasoning_budget_tokens`). A resolver maps this to the correct model-specific kwarg at request time. Gemma-4 uses `chat_template_kwargs.enable_thinking`. OpenAI-style models use `reasoning_effort`. New model families drop into the same resolver.

Default assignment:
- Chatter: `off`. Conversation stays fast.
- Scientist: `on`. Structured outputs, full thinking.
- Validator: `budget(2048)`. Bounded cost per participant turn.
- Analyst: `on`. Theme synthesis deserves the full budget.
- Ingest: `off`. Mechanical extraction.

Every LLM call is audited with `reasoning_content`, `reasoning_chars`, `reasoning_tokens`, `prompt_tokens`, `completion_tokens`, `latency_ms`, and status. When an LLM fails or returns empty content, the path raises. No silent fallbacks. No fabricated outlines.

## Stack

| Layer            | Choice                       | Why                                                                  |
| ---------------- | ---------------------------- | -------------------------------------------------------------------- |
| Backend          | FastAPI + Python 3.12 + uv   | Fast async, clean Pydantic types, reproducible locks                 |
| LLM routing      | LiteLLM Router               | One interface across OpenAI, Anthropic, local llama.cpp, LM Studio   |
| Persistent store | SurrealDB 2.x                | Documents, MTREE vector indexes, BM25 full-text, and graph edges    |
| Frontend         | SvelteKit + TypeScript + Tailwind | Small bundle, clear routing, fast dev loop                     |
| Streaming        | SSE for user-facing, WebSockets for agent-to-agent and large chunks | Right tool per traffic shape |
| Embeddings       | Nomic Embed Text v2 MoE (768 dim) | Local, good enough, free                                       |

## Quick start

```bash
# 1. Surreal up
docker compose -f infra/docker-compose.local.yml up -d surrealdb

# 2. Apply schema
cd services/api
uv run python -m agentic_survey.db.schema

# 3. Backend
SURVEY_REPOSITORY=surreal SURVEY_LLM_ENABLED=true \
  uv run uvicorn agentic_survey.main:app --host 127.0.0.1 --port 8100

# 4. Frontend (new terminal)
cd apps/web && npm install && npm run dev
```

Then open `http://localhost:5270`. Admin password is whatever you set in `.env`; see `.env.example` for the full contract.

## Repo layout

```
services/api/              FastAPI backend
  agentic_survey/
    agents/                Designer, Interviewer, Validator, Analyst
      prompts/             Brain-A and Brain-B prompts per surface
    api/                   HTTP routes (campaigns, invites, sessions, admin, models)
    db/                    SurrealDB wrapper + canonical schema
    engine/                State machine, session policy, saturation signals
    llm/                   LiteLLM router, catalog, reasoning resolver, callbacks
    repository.py          InMemoryRepository (test path)
    db/surreal_repository.py  SurrealRepository (production path)
apps/web/                  SvelteKit operator + participant shell
docker/                    Runtime container images
docs/                      Architecture notes, bundle contract, deployment guide
examples/product-bundles/  Demo product bundle
infra/                     docker-compose for local dev
```

## Principles

- **No silent errors.** Every LLM failure, every Surreal query failure, every parse failure raises. The route handler returns the error to the caller. Fallback code that fabricates answers is a bug.
- **SurrealDB is truth.** Post-migration, all persistent state lives there. In-memory is a test path only.
- **Structured pool backstage, conversational flow foreground.** The participant never sees the outline. Mira does.
- **Reasoning is an explicit toggle, not a side effect.** Every catalog entry declares its mode. No hidden thinking budgets.
- **No commits without user approval.** The runtime ships when the scientist says it ships.

## Stack status

Pre-1.0. Functional end-to-end:

- Backend + persistence + frontend boot cleanly against SurrealDB.
- Admin can design a campaign with real Brain B outlines from Gemma-4.
- Participants can redeem an invite, open `/chat/[session_id]`, and exchange real turns with Mira.
- Validator runs on every participant turn and stores its judgment on the turn.
- State survives uvicorn restart.

Still to build:
- Analyst HDBSCAN loop and saturation advisory.
- SSE streams for the live graph on `/admin/campaigns/[id]`.
- Knowledge ingestion (PDF, web, YouTube) into SurrealDB with MTREE indexing.
- `model_catalog` and `admin_session` persistence parity.
- Full test harness (currently paused).

## License

Apache 2.0 (see `LICENSE`).

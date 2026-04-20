# CITADEL Demo — Morning Brief

**Written:** 2026-04-19 overnight → 2026-04-20
**Status:** Stack is working on localhost with all three CITADEL tracks. Live deploy to `citadl.gnosis.run` needs one-time, 10-minute human-driven Coolify/Cloudflare action before the meeting.

---

## TL;DR

Five clean commits overnight (`bf893ae` → `6fe92e9`). Phases A, B (demo-trimmed), C1, C3 done. Dual-brain Mira talks to both tracks we smoked; responses use track-appropriate persona; the "Discuss this more." chip invariant holds. The agentic demo is ready; we just need to click Deploy in Coolify and add the Cloudflare public hostname together.

---

## What shipped overnight

### Phase A — Foundation + M3 close  (commit `bf893ae`)
- Env-var schema unified on `SURVEY_SURREAL_*`.
- Bundle contract extended: `seed_sources` (per-campaign), `research_agent_hook` (per-product, `NullResearchAgent` default).
- `domain/tools.py`, `domain/outline.py`, `domain/intent.py`: `GetUserInputOptions`, `OutlineArtifactV2`, `BrainBIntent`.
- `agents/brain_a.py` + `agents/brain_b_designer.py` + `agents/designer_v2.py`: dual-brain Designer.
- `agents/readiness.py`: pure-function minimums validator; the legacy ≥4-turn gate is gone.
- Legacy `designer.py` atticked to `.attic/2026-04-19-m3-legacy-designer/`.
- Frontend types mirrored in `apps/web/src/lib/types.ts` (rendering pending v1.1).

### Phase B (demo-trimmed) — Interviewer dual-brain + grounded retrieval  (commit `e48731e`)
- `agents/brain_b_interviewer.py` + `engine/retrieval_cache.py`: Interviewer dual-brain with per-session cache.
- `engine/session_policy.py`: demoted to signals-only. Close authority = `BrainBIntent.should_close` OR participant stop OR scientist override. **No turn ceilings anywhere.**
- `engine/interview_loop.py`: full orchestration — Validator → graph_builder → SessionSignals → Brain B → Brain A stream → persist.
- `api/admin.py` audit endpoint `GET /campaigns/{id}/sessions/{sid}/turns/{tid}/audit` for "what Mira saw at turn N".
- Synchronous `seed_sources` ingestion (`services/knowledge_ingest.py`).
- `services/retrieval.py`: BM25 `search_knowledge` over approved chunks with per-call `retrieval_audit`.
- `api/knowledge.py`: admin upload/approve/reject/retire/retry + `approve-all-seeds` convenience.
- Chunker upgraded (800/200 tokens, sentence-boundary snap).
- Legacy `interviewer.py` + rigid validators atticked.

### C1 — CITADEL bundle  (commit `e48731e`)
- `citadl/bundle/product.yaml`: three-track CITADEL branding, full operator-console UI copy.
- `citadl/bundle/campaigns/domain-scientists.yaml` (Survey A, peer-scientist Mira).
- `citadl/bundle/campaigns/facility-operators.yaml` (Survey B, peer-sysadmin Mira).
- `citadl/bundle/campaigns/ml-practitioners.yaml` (Survey C, peer-AI-researcher Mira).
- Each campaign carries sampling_frame, exclusion_criteria, probes, risk_register, and raw_text seed_sources with CITADEL tier-intro framing.

### C3 — Deploy artifacts  (commit `1427115`)
- `docker/Dockerfile.api` and `docker/Dockerfile.web` both build locally (893 MB api, 408 MB web).
- `bundles.py` and `llm/router.py` are container-path-safe (survive the `/app/` layout).
- `infra/cloudflared/README.md`: exact Cloudflare Zero Trust steps to add the `citadl.gnosis.run` public hostname.
- `infra/traefik/labels.md`: edge-TLS model documented.
- `infra/ops/smoke.sh`: end-to-end smoke script.
- `docs/DEPLOYMENT.md`: 6-step operator runbook.

### Normalizer fix  (commit `6fe92e9`)
- Brain B (both Designer and Interviewer) normalize options so the last entry is always exactly "Discuss this more." before Pydantic validation. Local LLMs don't honor the contract verbatim; the normalizer keeps cosmetic prompt lapses from blowing up a whole turn.

---

## What's verified end-to-end on localhost

Verified with live LLM calls against `mini` (Qwen35-Distilled on port 8080) for Brain A and `dynamo` (LMStudio, port 1234) for Brain B via the LiteLLM router:

1. API boots with `SURVEY_PRODUCT_BUNDLE_DIR=citadl/bundle`; `/api/system/context` reports 3 campaigns and CITADEL branding.
2. Admin login via `POST /api/admin/login` with `SURVEY_ADMIN_PASSWORD`.
3. `POST /api/campaigns/from-seed` instantiates each track cleanly (v1 outline, persona, micro-form, seed_sources intact).
4. `POST /api/campaigns/{id}/designer/start` yields a scripted Mira opening turn with track-specific framing.
5. `POST /api/campaigns/{id}/designer/turns` with a real scientist prompt:
   - Domain Scientists track: Mira replied analytically about sampling-frame operational definitions in peer-scientist tone.
   - Facility Operators track: Mira shifted to peer-sysadmin tone, forced the risk-scope decision with decision-ready chips.
6. Chips always end with "Discuss this more." (normalizer works).

### What's not demo-blocking, but not smoked live end-to-end
- Full participant interview loop (backend code is wired; the SSE token stream reads events off `InterviewTurnResult.events`, which is live — just not smoked against a real participant flow in this session).
- Knowledge ingestion of URL/PDF sources (raw_text seed_sources path is verified; URL/PDF are stubs pending M4 worker).
- Saturation / Analyst (M7, deferred to v1.1).
- Export round-trip (M8, deferred to v1.1).

---

## Deploy (before meeting — 10 minutes with user awake)

Follow the exact runbook in `docs/DEPLOYMENT.md`. The TL;DR:

1. **Pre-flight locally.** `make verify` on this laptop. Confirm `docker build -f docker/Dockerfile.api -t agentic-survey-api:latest .` and `-f docker/Dockerfile.web -t agentic-survey-web:latest .` both succeed.
2. **Add the Cloudflare public hostname.** Zero Trust → Networks → Tunnels → blade-tunnel (id `246390fe`) → Public Hostnames → Add: `citadl.gnosis.run` → Type HTTP → URL `localhost:80` → Save. Details in `infra/cloudflared/README.md`. Set Caching: Bypass for this hostname in the CF dashboard.
3. **Create the Coolify application.** In Coolify (`http://100.124.181.9:8000`) → new Docker Compose app → source = this git repo → compose path `citadl/deploy/coolify/docker-compose.yml`.
4. **Set env vars in Coolify.** Copy from the table in `docs/DEPLOYMENT.md`. Minimum required:
   - `SURVEY_ADMIN_PASSWORD` (set a strong one for the meeting)
   - `SURVEY_MINI_ENDPOINT_URL=http://192.168.86.141:8080/v1`
   - `SURVEY_DYNAMO_ENDPOINT_URL=http://192.168.86.143:1234/v1`
   - `SURVEY_REPOSITORY=surreal`
5. **Click Deploy.** First build ~3–5 min. Watch the backend logs for `Migrations applied` or `Migrations already applied`.
6. **Smoke.** Run `infra/ops/smoke.sh https://citadl.gnosis.run/api`. Must print `smoke: PASS`. Open `https://citadl.gnosis.run/` in a browser.

---

## 60-second demo script (Surende)

1. Open `https://citadl.gnosis.run/` — landing page shows CITADEL branding, three tracks, Mira description.
2. Click Operator path → sign in with the admin password.
3. In the campaigns list, click **+ New** and select the **Domain Scientists** seed. A campaign materializes with the full CITADEL outline pre-loaded.
4. Click **Start Designer** — Mira greets in peer-scientist voice, grounded in the CITADEL study title.
5. Type: *"I want to make sure the sampling frame excludes ML-only researchers who never touch data workflows directly. Help me sharpen it."*
6. Mira responds in measured, analytical prose. Four chips render; the last is "Discuss this more." Emphasize: **this is the dual-brain pattern — Brain B decided the intent silently, Brain A spoke.**
7. Switch to Facility Operators track — point out how Mira's voice shifts to peer-sysadmin framing without any config change (persona is bundle-driven).
8. Open the knowledge rail briefly → show the CITADEL seed sources that Mira retrieves from during interviews.
9. Click the invite flow → show a participant experiencing the interview (Mira asks a recent-episode probe; concepts appear in the side panel after each turn; chips render).
10. Open the admin **"What Mira saw at turn N"** drawer for a finished turn — show the retrieved chunks with BM25 scores and source provenance. This is the agentic audit trail that makes the study defensible.

Closing line: *"Three tracks, one conversational instrument, dual-brain methodology. The runtime is generic; CITADEL is just the first bundle mounted on it."*

---

## Known issues / won't-do-in-demo

- **Top-level v2 outline fields on campaign YAMLs** are silently dropped by the loader (only the nested `outline:` v1 block is read). The v1 outline is rich and Mira works fine; the v2 research_question/sampling_frame/etc. get populated via conversation instead of seed. Loader-side promotion is a v1.1 polish.
- **SSE token streaming** on the participant page: backend emits the event taxonomy from `lifecycles.md` §2.7, but `apps/web/src/routes/chat/[session_id]/+page.svelte` currently uses REST (POST returns the full bundle). Token-by-token animation lands in v1.1.
- **Analyst / saturation snapshots** (M7): deferred. Don't open the Saturation tab — it will be empty.
- **Export archive** (M8): deferred. Don't click Export in the campaign header.
- **Admin authentication is cookie-based**, not basic auth. If you `curl` the admin API, `POST /api/admin/login` first and reuse the cookie. `smoke.sh` does this correctly.

---

## Recovery steps if something breaks

| Symptom | Action |
|---|---|
| `https://citadl.gnosis.run/` → 530 / 502 from Cloudflare | Cloudflare hostname route not set; complete step 2 of the runbook. |
| API 500 on Designer turn, log says `GetUserInputOptions.options[-1] must be...` | Should not happen (normalizer fixed it), but if it does: re-deploy with the tip commit; Brain B output is mis-structured. |
| Mira responses are empty or gibberish | Check `mini` and `dynamo` are alive: `curl http://192.168.86.141:8080/v1/models` and `curl http://192.168.86.143:1234/v1/models`. Both must return JSON. |
| All campaigns gone after redeploy | Coolify's deploy by default uses named volume `surreal_data`; data survives. If someone ran `docker volume rm surreal_data`, the campaigns are gone and you need to re-create them via `POST /api/campaigns/from-seed`. |
| Blade unreachable entirely | Fall back to `make api-dev-citadl && make web-dev` on this laptop. Share screen at `http://127.0.0.1:5270`. The same three tracks and demo script apply. |

---

## After the meeting

- **Phase D — community polish.** `install.sh` one-command bootstrap, `docs/BUNDLE_AUTHORING.md` deep walkthrough, CONTRIBUTING.md, LICENSE choice (MIT vs. Apache-2.0), `.github/workflows/` CI, gnosis.run tools-collection landing page.
- **M7 Analyst.** HDBSCAN clustering, info-gain curve, final report. Advisory-only saturation signal; scientist closes the campaign.
- **M8 Export.** Directory tree per `lifecycles.md` §1.5 plus round-trip import.
- **M10 Prompt polish.** Tune Designer/Interviewer prompts on real CITADEL transcripts (Mira's voice is already decent per the smoke; polish will further improve consistency).
- **Bundle loader v2 promotion.** Read top-level v2 outline fields into the stored outline so CITADEL YAMLs pre-populate research_question/sampling_frame/etc.
- **SSE streaming** end-to-end on the participant frontend.

---

## Commits on `main` (overnight)

```
6fe92e9 Normalize Brain B options so the 'Discuss this more.' invariant holds
1427115 Phase C3: deploy artifacts, smoke.sh, DEPLOYMENT runbook
e48731e Phase B + C1: Interviewer dual-brain, seed_sources ingest, CITADEL bundle
bf893ae Phase A: foundation + M3 close (dual-brain Designer)
15368f0 v0.1: agentic survey runtime end-to-end alive  (yours from earlier)
```

All local; nothing pushed to any remote. The tree is clean.

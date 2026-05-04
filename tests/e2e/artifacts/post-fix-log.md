# Post-fix log — Phase 1 (planner / prompt fixes)

Author: Claude Opus 4.7. Branch: `main`. HEAD before Phase 1: `4e103f4 M11.17`.

Status: **CODE COMPLETE — awaiting human approval before live smoke and Phase 2.**

## What changed

### 1.1 — Axis rotation gate (planned commit M11.18)

**Files**
- `services/api/agentic_survey/agents/prompts/interviewer_brain_b.md` — added "Axis rotation rule" section. Spells out: rotate when prior axis has been the focus for 2+ consecutive turns AND any other rubric axis has score 0.0; rotate immediately when participant signals bridging.
- `services/api/agentic_survey/agents/brain_b_loop.py` — new `_force_axis_rotation(intent, *, rubric_axes, prior_active_axis_prefix, prior_consecutive_count, surface) -> tuple[BrainBIntent, bool]`. Fires when the model emits the same axis prefix on the third consecutive turn; rewrites `active_axis` to the lowest-numbered rubric axis whose score is 0.0. Rotation skips the floor bump on the same turn so a freshly-rotated axis is not credited with prior-axis evidence.
- `services/api/agentic_survey/agents/brain_b_interviewer.py` — new kwargs `prior_active_axis_prefix`, `prior_consecutive_active_axis_count`. Emitted into the system prompt context as "Axis rotation context" so the model sees the counter on every turn.
- `services/api/agentic_survey/engine/interview_loop.py` — new helper `_consecutive_active_axis_history(session) -> tuple[str, int]` walks turns newest-first; both values feed Brain B per turn.
- `services/api/tests/unit/test_brain_b_loop.py` — five new tests including `test_axis_rotation_after_two_consecutive_turns_on_same_axis` (the spec's named acceptance test).
- `services/api/tests/unit/test_axis_history.py` — five new tests for the orchestrator-side history helper.

### 1.2 — Closing prose guard + finish wiring (planned commit M11.19)

**Files**
- `services/api/agentic_survey/agents/prompts/interviewer_brain_b.md` — added "Closing turn contract" section. Demands prose-state coherence and the 2-chip closing set.
- `services/api/agentic_survey/agents/brain_b_loop.py` — new `_apply_closing_prose_guard(intent, *, reply_text)`. Scans the spoken reply against an allowlist of closing phrases; when matched and `should_close=False`, forces `should_close=True`, `closing=True`, and rewrites chips to `["End conversation", "Discuss this more."]`. Logs `closing prose detected; forced should_close=true` at WARNING.
- `services/api/agentic_survey/engine/interview_loop.py` — calls the guard right after Brain A's stream completes, before the agent turn is appended. The corrected intent flows into the persisted turn.
- `services/api/agentic_survey/domain/tools.py` — `GetUserInputOptions.options` lower bound dropped from `min_length=3` to `min_length=2` so the closing pair is schema-valid.
- `services/api/agentic_survey/api/sessions.py` — `POST /sessions/{sid}/finish` now uses `_require_session_access`. Participant tokens close their own session as `participant_self_close`; admin tokens still close as `scientist_override`.
- `apps/web/src/routes/chat/[session_id]/+page.svelte` — `submitTurn` special-cases the chip text `"End conversation"` and routes to a new `finishSession()` helper that POSTs to `/api/sessions/{sid}/finish`. The chat bundle is patched in place from the response.
- `services/api/tests/unit/test_brain_b_loop.py` — four new tests including `test_closing_prose_forces_should_close` (the spec's named acceptance test) and tests for "thanks for the time" phrasing, no-op on substantive replies, and idempotence.
- `services/api/tests/unit/test_domain_types.py` — adjusted `test_get_user_input_options_rejects_too_few_options` to use a single-option payload (the new lower bound), and added `test_get_user_input_options_accepts_closing_pair`.

### 1.3 — Chip grounding rule + filter (planned commit M11.20)

**Files**
- `services/api/agentic_survey/agents/prompts/interviewer_brain_b.md` — added "Chip grounding rule" describing the noun-overlap requirement and listing rejected generic vocabulary.
- `services/api/agentic_survey/agents/brain_b_loop.py` — extended `_normalize_discuss_more` with two new kwargs (`last_participant_message`, `participant_extracted_concepts`), a `_grounding_corpus` helper that builds a token / phrase set, and a `_chip_is_grounded` helper that does case-insensitive substring matching for multi-word concepts and word-boundary matching for single tokens. Empty corpus (cold start) skips the filter. **Fallback**: if every chip fails grounding, the filter saves the first ungrounded chip as a single anchor so the schema's `min_length=2` is honored — without the fallback, an empty cleaned list led to a single-option payload that fails Pydantic validation in production.
- `services/api/agentic_survey/agents/brain_b_interviewer.py` — pipes the new kwargs through to `run_brain_b_with_tools`.
- `services/api/agentic_survey/engine/interview_loop.py` — new helper `_last_participant_grounding(session) -> tuple[str, list[str]]` reads the most recent participant turn's text and validator `extracted_concepts` labels.
- `services/api/tests/unit/test_brain_b_loop.py` — four new tests covering: drop abstract chips when participant context is concrete; pass-through on cold start; phrase-aware concept-label matching; the all-dropped fallback path keeps one anchor so options stays at the schema floor.

### 1.4 — `?debug=1` propagation through CITADL Console link (planned commit M11.21)

**Files**
- `apps/web/src/routes/+layout.svelte` — Workspace link now reactive: when `?debug=1` is present in the current URL, the `next` redirect target is encoded as `/admin/campaigns?debug=1` so the post-login redirect preserves the flag. Previously the link was hard-coded to drop the param.

### 1.5 — `--reload` cookie loss (planned commit M11.21 or rolled into 1.4)

**Files**
- `docs/MIRA-ROADMAP.md` — sharpened gotcha #14 to explicitly say smoke runs should drop `--reload`.

## Verification — local

- `cd services/api && uv run pytest -q` — **301 passed** (was 282 baseline + 19 new tests). 0 failed.
- `make verify` — green: 301 unit tests, svelte-check 0 errors / 0 warnings, web build clean (chat page ~7.4 kB SSR).
- `npm run check` (web) — 0 errors, 0 warnings.

## Verification — live (PENDING)

Live three-persona smoke against the real LM Studio endpoints is **not yet run**. Recommended protocol:

1. Restart stack without `--reload` per gotcha #14 amendment:
   ```bash
   docker compose -f infra/docker-compose.local.yml down -v
   docker compose -f infra/docker-compose.local.yml up -d surrealdb
   cd services/api && uv run python -m agentic_survey.db.schema && cd -
   SURVEY_REPOSITORY=surreal SURVEY_LLM_ENABLED=true \
     SURVEY_PRODUCT_BUNDLE_DIR=$(pwd)/citadl/bundle \
     nohup uv run --project services/api uvicorn agentic_survey.main:create_app \
     --factory --host 127.0.0.1 --port 8100 --log-level info \
     > /tmp/api-dev.log 2>&1 &
   ```
2. Re-run the three persona journeys from `tests/e2e/PRE-DEPLOY-VERDICT.md`, save fresh artifacts under `tests/e2e/artifacts/post-fix-session-{A,B,C}-*/`.
3. Diff `axes_coverage` progression: rotation should fire at least 4 different axes per session within the first 8 agent turns; at least one session should hit a natural close (`should_close=true` + status=closed).
4. Re-export `answers.csv` and `answers.jsonl`. Coverage rate per session ≥ 30 % of applicable Tier-A questions for ≥ 2 of 3 sessions.
5. Tail `/tmp/api-dev.log` for new audit lines:
   - `brain_b axis rotation forced` — should appear at least once across the 3 sessions if the rotation gate is doing work.
   - `closing prose detected; forced should_close=true` — should appear if any session prose-closes; safe to be 0 if all sessions close cleanly with model-side `should_close=True`.
   - `brain_b chip grounding filter dropped chips` — informational.

If those signals do not improve over the original E2E baseline, stop and diagnose before commit.

## Stop condition reached

Per the spec's stop conditions:
> You have completed Phase 1 and want a human review before starting Phase 2.

The code is staged for review. Suggested commits in order:

| Commit | Subject | Files |
|--------|---------|-------|
| M11.18 | enforce axis rotation gate after 2 consecutive same-axis turns | brain_b_loop.py, brain_b_interviewer.py, interview_loop.py, prompts/interviewer_brain_b.md, test_brain_b_loop.py, test_axis_history.py |
| M11.19 | reconcile closing prose with should_close + finish wiring | brain_b_loop.py, interview_loop.py, prompts/interviewer_brain_b.md, domain/tools.py, api/sessions.py, chat/[session_id]/+page.svelte, test_brain_b_loop.py, test_domain_types.py |
| M11.20 | drop ungrounded chips against participant noun corpus | brain_b_loop.py, brain_b_interviewer.py, interview_loop.py, prompts/interviewer_brain_b.md, test_brain_b_loop.py |
| M11.21 | propagate ?debug=1 through workspace link + reload gotcha note | apps/web/src/routes/+layout.svelte, docs/MIRA-ROADMAP.md |

Because three of the four commits touch the same Python files (`brain_b_loop.py`, `brain_b_interviewer.py`, `interview_loop.py`, `prompts/interviewer_brain_b.md`, `test_brain_b_loop.py`), strict file-per-commit splitting is not possible without rewinding and re-editing. The cleanest path is one squashed commit (e.g., `M11.18: planner + prompt fixes (rotation, closing prose, chip grounding) + debug query propagation`) with the diff readable as four discrete sections. The human can choose either path.

Awaiting decision on:
- Run live smoke now or after Phase 2?
- Single squashed commit (`M11.18`) or four sequential commits?
- Proceed to Phase 2 (participant UX redesign) immediately or pause for review?

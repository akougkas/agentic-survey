# Phase 2 Polish — Redesign Log

This log covers the polish pass on top of `7695a00 M11.22: phase 2 participant
surface redesign`. The structural redesign in 7695a00 was functional but not
mobile-grade and lacked modern chat experience polish; this commit
(`M11.23: phase 2 polish`) closes those gaps.

## Files touched

```
apps/web/src/app.css                                    rewrite + new tokens
apps/web/src/routes/+layout.svelte                      skip-link, main landmark
apps/web/src/routes/+page.svelte                        SVG arrow, persona pull quote
apps/web/src/routes/about/+page.svelte                  unchanged
apps/web/src/routes/invite/+page.svelte                 NEW (no-token stub)
apps/web/src/routes/invite/[token]/+page.svelte         submit arrow + spinner
apps/web/src/routes/chat/[session_id]/+page.svelte      focus trap, alertdialog,
                                                        optimistic rollback,
                                                        connected-state forwarding,
                                                        retrieval count badge,
                                                        modal autofocus + restore
apps/web/src/lib/components/ChatPane.svelte             auto-resize, Cmd+Enter,
                                                        smooth scroll, aria-live,
                                                        pending rail, chip pressed,
                                                        disconnect banner
apps/web/src/lib/runtime-copy.ts                        coverage_empty fallback
```

## Fix area summary

### A. Mobile blockers (DONE)

- A1 Touch targets bumped to ≥ 44px at every viewport.
  `.transcript-end` `min-height:44px`. `.chip` padding `py-2`. `.chip-discuss`
  uses 12px vertical padding with negative margins so the visible glyph stays
  compact while the tap area expands to meet the 44pt target.
  `.working-notes-summary` `py-3 min-height:44px`. `.select-row` `py-3
  min-height:44px`. `.consent-card` `min-height:44px`. `.button-primary`,
  `.button-secondary`, `.button-danger` all carry `min-height:44px`.
  `.participant-wordmark` and `.participant-attribution` use `inline-flex
  items-center min-height:44px` so the masthead links remain tappable while
  visually compact. Audited live at 414×896: zero failures.
- A2 `bundle.campaign.title` truncated at the em-dash for narrow widths.
  `ChatPane` exposes `shortTitle` derived from `title.split(/[–—]/)[0]` and
  switches between full and short via `hidden sm:inline` / `sm:hidden`. With
  the demo bundle (no em-dash), the full title remains. Verified:
  `CITADL Community Pulse` renders at 414, `CITADL Community Pulse — Adaptive
  Interviews on the Future of Agentic Data Lifecycle Management` renders ≥ sm.
- A3 Modal width clamped via `max-width: min(28rem, calc(100vw - 2rem))`.
  Verified at 414: modal is 357px wide on a 409px viewport.
- A4 Focus trap implemented inline on `.modal-card` via `handleModalKeydown`.
  Tab from last focusable wraps to first; Shift+Tab from first wraps to last.
  Esc dismisses.
- A5 Modal opens with focus on the safe `Keep talking` button (autofocus via
  `bind:this` + `tick()` + `focus()`). The destructive `End conversation`
  button does not autofocus. Last-focused-before-modal is restored on close.
- A6 `:focus-visible` outline rings added globally in the base layer using a
  2px moss outline with 2px offset. Specific landing-path and consent-card
  selectors carry custom focus styling for visual continuity.

### B. Modern chat experience (DONE)

- B1 Textarea auto-resizes on `input` event up to 50vh. Verified: typed 8
  lines, height grew from 80px → 184px, capped at 298.88px (50vh on a
  598px-tall viewport). On submit / clear, height resets.
- B2 `Cmd+Enter` (metaKey) and `Ctrl+Enter` both submit; plain `Enter`
  inserts a newline. Verified live: dispatched `keydown` with `metaKey:true`
  cleared the textarea (handleSubmit ran); plain Enter did not.
- B3 Smooth scroll on new turns via `scrollTo({ behavior: 'smooth' })`. The
  reduced-motion guard (`@media (prefers-reduced-motion: reduce)`) overrides
  scroll behavior to instant.
- B4 Optimistic-turn rollback: `submitTurn` tags the optimistic turn with
  `pending-${ts}` and on caught error filters that turn out before showing
  the error message.
- B5 `aria-live="polite"` on `.transcript-body` + a separate sr-only live
  region that mirrors the latest agent role label and first sentence.
- B6 Pending agent turn renders with a subtle moss left-rail pulse
  (`@keyframes rail-pulse`) plus the dot-pulse. Reduced-motion disables both.
- B7 SSE inspection: the backend stream emits event-level frames only
  (`brain_b_planned`, `validator_scored`, `concepts_extracted`,
  `graph_delta`, `turn_complete`, `session_finished`, `session_paused`).
  No token-level streaming on the agent's prose. The current "round-trip
  then full message" UI is the contract. No changes required.
- B8 Disconnect banner: a 3-second grace timer arms when SSE drops; once it
  fires, `connected=false` flows to `ChatPane` which shows
  `connection lost · retrying` next to the turn counter. `onopen` resets it.
- B9 Chip pressed feedback: tapping a chip sets `pressedChip` for 220ms
  which adds the `chip--pressed` class (`background: rgba(126,184,141,0.22)`).
  The submit dispatches immediately so the visible flash doesn't block.
- B10 End-conversation confirmation button shows an inline `dot-pulse` next
  to "Closing" while `endPending` is true.

### C. Working notes ledger (DONE)

- C1 Axis labels render inline beneath each rubric row when `[open]`. The
  short-form label is derived by stripping the `R# —` prefix. Touch users
  can now read the axis without hover.
- C2 Empty-state copy fallback added in `runtime-copy.ts`
  (`coverage_empty: 'Mira will tally questions as you go.'`). Renders when
  the satisfied-question count is zero.
- C3 Working-notes summary uses `flex-1 truncate` on the eyebrow and
  `shrink-0` on the chevron so the toggle stays visible at narrow widths.
- C4 Retrieval card now leads with a moss `.badge-count` pill carrying the
  retrieved-passage count alongside the existing prose.

### D. Landing / about / invite refinement (DONE)

- D1 `apps/web/src/routes/invite/+page.svelte` added as a no-token stub
  with a quiet two-paragraph reading panel.
- D2 Landing path-card hover now also fades a subtle moss tint
  (`hover:bg-[color:rgba(126,184,141,0.04)]`) and animates the arrow with
  a 140ms ease-out translate.
- D3 ASCII `→` swapped for an inline 16×10 SVG arrow on landing path cards
  and on the invite submit button.
- D4 Consent card hover lightens the border to
  `rgba(232,224,207,0.24)` (token unchanged, verified at three widths).
- D5 Invite submit button now leads with `Begin the conversation →`
  (SVG arrow inline) and shows a `dot-pulse` while pending.
- D6 Persona aside renders the first sentence of `persona_panel_description`
  as an italic display-serif pull quote, with the trailing prose below in
  the muted body. With the CITADL bundle the lead reads
  `Mira is a single adaptive field researcher.`

### E. Hygiene (DONE)

- E1 Font preload: the platform relies on system fonts (`Iowan Old Style`,
  `Avenir Next`, `SFMono`) per `tailwind.config.ts`. No web-loaded fonts
  exist, so there is no FOUT/FOIT to mitigate; documented here.
- E2 `app.css` rewritten with a single source-ordered structure:
  base + theme → layout primitives → editorial primitives → form primitives
  → landing → invite → chat transcript → working notes + closing → modal
  → animations → legacy admin tokens → reduced motion. The pre-existing
  duplicate `.chip` definition that was shadowing the participant pill
  styling has been removed; `.chip` is now the single rounded-full pill.
- E3 `@media (prefers-reduced-motion: reduce)` overrides animation duration,
  iteration, and transition globally and disables `dot-pulse`,
  `rail-pulse`, `disconnect-pulse`, and `transcript-body` smooth scroll.
- E4 Skip-to-content link added to `+layout.svelte` as the first child.
  Sr-only until focused; on focus jumps to fixed `top:1rem left:1rem`.
  `<main id="main">` wraps the slot in both admin and participant branches.
- E5 Textarea `aria-describedby="transcript-instructions"` wires the footer
  note as the contextual instruction.
- E6 Modal upgraded from `role="dialog"` to `role="alertdialog"` with
  `aria-describedby` linking the body. Validated live.

### F. Verification

- `cd apps/web && npm run check` — 0 errors, 0 warnings.
- `cd apps/web && npm run build` — adapter-node build clean, 5.46s.
- Three-width browser walk performed at 414×896, 768×1024, and 1440×900.
  No horizontal overflow at any width. Touch-target audit at 414 returned
  zero failures across landing, /invite, /invite/[token], and
  /chat/[session_id]. Modal verified to fit within viewport with focus
  trap, autofocus on safe button, and Esc dismissal working.
- Bundle-swap verification (F1) **DEFERRED**. Performing it requires
  restarting the API on port 8100, which the polish brief forbids without
  explicit human permission. Once approved, run:
  ```bash
  pkill -f 'uvicorn agentic_survey.main:create_app'
  SURVEY_REPOSITORY=surreal SURVEY_LLM_ENABLED=true \
    SURVEY_PRODUCT_BUNDLE_DIR=$(pwd)/examples/product-bundles/demo \
    nohup uv run --project services/api uvicorn agentic_survey.main:create_app \
    --factory --host 127.0.0.1 --port 8100 --log-level info \
    > /tmp/api-dev-demo.log 2>&1 &
  ```
  The em-dash truncation rule in ChatPane handles bundles without an
  em-dash gracefully (the regex `split(/[–—]/)` returns the whole string
  when no match). The demo title `Structured interview campaigns with
  Mira.` will render unchanged at all widths.
- Persisted screenshots (F2): the chrome MCP `save_to_disk` parameter does
  not produce findable on-disk files in this environment. Visual evidence
  was captured via JS-side measurements documented inline.

## Token additions in `app.css`

```
.skip-link, .skip-link:focus
.transcript-eyebrow                  truncated eyebrow at narrow widths
.transcript-disconnect, .transcript-disconnect-dot
.transcript-textarea                 auto-resize composer with min/max-height
.turn--pending                       moss-rail pulse during agent compose
.rubric-axis-label                   inline R# label under each rubric row
.working-notes-summary-label         truncatable eyebrow with shrink-0 chevron
.working-notes-retrieved-row         flex row for badge + text
.badge-count                         small moss pill for retrieval count
.chip:active, .chip.chip--pressed    pressed-state visual flash
.landing-aside-quote                 italic display-serif persona pull quote
@keyframes rail-pulse, disconnect-pulse
@media (prefers-reduced-motion: reduce) { ... }
```

## Removed

- The duplicate `.chip` declaration that was shadowing the participant pill
  styling. The single remaining declaration is the rounded-full pill.

## Staged commit

`M11.23: phase 2 polish — mobile, modern chat experience, accessibility`

<script lang="ts">
  import { page } from '$app/stores';
  import { onDestroy, onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import ChatPane from '$lib/components/ChatPane.svelte';
  import { runtimeCopy } from '$lib/runtime-copy';
  import type {
    BrainBIntent,
    InterviewSessionRecord,
    InterviewTurnRecord,
    SessionBundleResponse,
    SurveyQuestion,
    ValidationSnapshot
  } from '$lib/types';

  let bundle: SessionBundleResponse | null = null;
  let sessionId = '';
  let loading = true;
  let sendPending = false;
  let resumePending = false;
  let error = '';

  $: sessionId = $page.params.session_id ?? '';
  $: bundleChat = $page.data.runtimeContext?.ui.chat ?? null;
  $: chatCopy = {
    header_eyebrow: bundleChat?.header_eyebrow ?? runtimeCopy.chat.header_eyebrow,
    header_wordmark: bundleChat?.header_wordmark ?? runtimeCopy.chat.header_wordmark,
    header_subline: bundleChat?.header_subline ?? runtimeCopy.chat.header_subline,
    page_title: bundleChat?.page_title ?? runtimeCopy.chat.page_title,
    conversation_heading: bundleChat?.conversation_heading ?? runtimeCopy.chat.conversation_heading,
    transcript_locked_label:
      bundleChat?.transcript_locked_label ?? runtimeCopy.chat.transcript_locked_label,
    agent_composing_label: bundleChat?.agent_composing_label ?? runtimeCopy.chat.agent_composing_label,
    working_notes_eyebrow: bundleChat?.working_notes_eyebrow ?? runtimeCopy.chat.working_notes_eyebrow,
    working_notes_heading: bundleChat?.working_notes_heading ?? runtimeCopy.chat.working_notes_heading,
    retrieved_heading: bundleChat?.retrieved_heading ?? runtimeCopy.chat.retrieved_heading,
    retrieved_description_singular:
      bundleChat?.retrieved_description_singular ?? runtimeCopy.chat.retrieved_description_singular,
    retrieved_description_plural:
      bundleChat?.retrieved_description_plural ?? runtimeCopy.chat.retrieved_description_plural,
    concepts_heading: bundleChat?.concepts_heading ?? runtimeCopy.chat.concepts_heading,
    concepts_empty: bundleChat?.concepts_empty ?? runtimeCopy.chat.concepts_empty,
    turn_counter_template: bundleChat?.turn_counter_template ?? runtimeCopy.chat.turn_counter_template,
    active_footer: bundleChat?.active_footer ?? runtimeCopy.chat.active_footer,
    paused_footer: bundleChat?.paused_footer ?? runtimeCopy.chat.paused_footer,
    finished_footer: bundleChat?.finished_footer ?? runtimeCopy.chat.finished_footer,
    session_complete_eyebrow:
      bundleChat?.session_complete_eyebrow ?? runtimeCopy.chat.session_complete_eyebrow,
    return_home_label: bundleChat?.return_home_label ?? runtimeCopy.chat.return_home_label,
    empty_state: bundleChat?.empty_state ?? runtimeCopy.chat.empty_state,
    placeholder_default: bundleChat?.placeholder_default ?? runtimeCopy.chat.placeholder_default,
    placeholder_with_chips:
      bundleChat?.placeholder_with_chips ?? runtimeCopy.chat.placeholder_with_chips,
    submit_idle: bundleChat?.submit_idle ?? runtimeCopy.chat.submit_idle,
    submit_pending: bundleChat?.submit_pending ?? runtimeCopy.chat.submit_pending,
    submit_finished: bundleChat?.submit_finished ?? runtimeCopy.chat.submit_finished
  };
  $: isFinished = bundle?.session.status === 'finished';
  $: isPaused = bundle?.session.status === 'paused';
  $: activePrompt = bundle && bundle.session.status === 'active'
    ? [...bundle.session.turns]
        .reverse()
        .find((turn) => turn.role === 'agent' && turn.get_user_input)?.get_user_input ?? null
    : null;
  $: closingTurn = bundle
    ? [...bundle.session.turns].reverse().find((turn) => turn.role === 'agent' && turn.validation?.closing) ??
      [...bundle.session.turns].reverse().find((turn) => turn.role === 'agent') ??
      null
    : null;
  $: latestAgentIntent = bundle
    ? [...bundle.session.turns]
        .reverse()
        .find((turn) => turn.role === 'agent' && turn.brain_b_intent)?.brain_b_intent ?? null
    : null;
  $: participantTurnCount = bundle
    ? bundle.session.turns.filter((t) => t.role === 'participant').length
    : 0;
  $: rubricRows = bundle
    ? coverageByAxis(
        bundle.session.turns,
        bundle.campaign.outline.axes ?? [],
        bundle.session.next_plan ?? null
      )
    : coverageByAxis([], [], null);
  $: satisfiedQuestionPrompts = bundle
    ? satisfiedQuestions(latestAgentIntent, bundle.campaign.outline.question_bank ?? [])
    : [];
  $: statusTone = bundle
    ? bundle.session.status === 'active'
      ? 'moss'
      : bundle.session.status === 'paused'
        ? 'brass'
        : 'neutral'
    : 'neutral';
  $: sessionTitle = bundle ? truncate(bundle.campaign.title, 60) : '';
  $: attributionLabel = bundle
    ? bundle.session.consent_mode === 'anonymous'
      ? 'Anonymous'
      : `Attributed as ${bundle.session.identity_label || 'participant'}`
    : '';
  $: retrievalChunkCount = latestAgentIntent?.retrieval_chunks?.length ?? 0;
  $: retrievalMessage =
    retrievalChunkCount === 1
      ? chatCopy.retrieved_description_singular
      : chatCopy.retrieved_description_plural.replace('{count}', String(retrievalChunkCount));
  $: turnCounterText = chatCopy.turn_counter_template.replace(
    '{count}',
    String(participantTurnCount)
  );
  $: satisfiedQuestionCountText =
    satisfiedQuestionPrompts.length === 1
      ? '1 question covered'
      : `${satisfiedQuestionPrompts.length} questions covered`;
  $: footerNote = isFinished
    ? chatCopy.finished_footer
    : isPaused
      ? chatCopy.paused_footer
      : chatCopy.active_footer;
  $: placeholderText = isFinished
    ? 'This session is complete.'
    : isPaused
      ? 'Resume the session to continue.'
      : activePrompt && activePrompt.options.length
        ? chatCopy.placeholder_with_chips
        : chatCopy.placeholder_default;
  $: submitLabelText = isFinished
    ? chatCopy.submit_finished
    : sendPending
      ? chatCopy.submit_pending
      : chatCopy.submit_idle;

  function truncate(text: string, max: number): string {
    if (!text) return '';
    return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
  }

  function axisPrefix(raw: string): string {
    const trimmed = (raw ?? '').trim();
    const match = trimmed.match(/^R\d+/i);
    return match ? match[0].toUpperCase() : trimmed.slice(0, 2).toUpperCase();
  }

  function coverageByAxis(
    turns: InterviewTurnRecord[],
    outlineAxes: string[],
    nextPlan: BrainBIntent | null
  ): Array<{ key: string; score: number; fullLabel: string }> {
    // Prefer the freshest pre-plan if present; otherwise fall back to the
    // latest agent turn's committed intent (which is what rendered the
    // current visible reply).
    const plannedCoverage = nextPlan?.axes_coverage;
    const latestTurn = [...turns]
      .reverse()
      .find((t) => t.role === 'agent' && t.brain_b_intent?.axes_coverage);
    const coverageList =
      plannedCoverage && plannedCoverage.length > 0
        ? plannedCoverage
        : latestTurn?.brain_b_intent?.axes_coverage ?? [];

    const scoreByPrefix = new Map<string, number>();
    for (const entry of coverageList) {
      const prefix = axisPrefix(entry.axis);
      if (!scoreByPrefix.has(prefix)) {
        scoreByPrefix.set(prefix, entry.score ?? 0);
      }
    }

    const labelByPrefix = new Map<string, string>();
    for (const axis of outlineAxes ?? []) {
      const prefix = axisPrefix(axis);
      if (!labelByPrefix.has(prefix)) {
        labelByPrefix.set(prefix, axis);
      }
    }

    const rows: Array<{ key: string; score: number; fullLabel: string }> = [];
    for (let i = 1; i <= 8; i += 1) {
      const key = `R${i}`;
      const score = scoreByPrefix.get(key) ?? 0;
      let fullLabel = labelByPrefix.get(key);
      if (!fullLabel) {
        const match = coverageList.find((c) => axisPrefix(c.axis) === key);
        fullLabel = match?.axis ?? key;
      }
      rows.push({ key, score, fullLabel });
    }
    return rows;
  }

  function satisfiedQuestions(
    intent: BrainBIntent | null,
    questionBank: SurveyQuestion[]
  ): string[] {
    if (!intent?.question_coverage?.length) return [];
    const promptById = new Map(questionBank.map((question) => [question.id, question.prompt]));
    const prompts: string[] = [];
    for (const entry of intent.question_coverage) {
      if (entry.status !== 'satisfied') continue;
      const prompt = promptById.get(entry.question_id);
      if (!prompt) continue;
      prompts.push(truncate(prompt, 120));
    }
    return prompts;
  }

  // --- SSE plumbing -------------------------------------------------------
  // One persistent EventSource per session. The browser handles Last-Event-ID
  // replay on reconnect automatically; we only need to reopen the socket with
  // a modest backoff when the server drops us.
  let eventSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelayMs = 1000;
  let streamClosed = false;

  function patchNextPlan(plan: BrainBIntent | null): void {
    if (!bundle) return;
    bundle = {
      ...bundle,
      session: { ...bundle.session, next_plan: plan }
    };
  }

  function patchTurnValidation(turnId: string, validation: ValidationSnapshot): void {
    if (!bundle) return;
    const turns = bundle.session.turns.map((turn) =>
      turn.id === turnId ? { ...turn, validation } : turn
    );
    bundle = {
      ...bundle,
      session: { ...bundle.session, turns }
    };
  }

  function patchSessionStatus(
    status: InterviewSessionRecord['status'],
    closeReason?: string | null
  ): void {
    if (!bundle) return;
    bundle = {
      ...bundle,
      session: {
        ...bundle.session,
        status,
        close_reason: closeReason ?? bundle.session.close_reason
      }
    };
  }

  function handleStreamEvent(name: string, raw: string): void {
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    switch (name) {
      case 'brain_b_planned': {
        const plan = (data.next_plan ?? null) as BrainBIntent | null;
        patchNextPlan(plan);
        return;
      }
      case 'validator_scored': {
        const turnId = typeof data.turn_id === 'string' ? data.turn_id : '';
        const validation = (data.validation ?? null) as ValidationSnapshot | null;
        if (turnId && validation) {
          patchTurnValidation(turnId, validation);
        }
        return;
      }
      case 'concepts_extracted':
      case 'graph_delta':
      case 'turn_complete':
        // No-op on the chat page: validator_scored already carries the
        // concept payload, the admin graph view owns graph_delta, and the
        // POST response already closed the foreground turn.
        return;
      case 'session_finished': {
        const closeReason =
          typeof data.close_reason === 'string' ? data.close_reason : null;
        patchSessionStatus('finished', closeReason);
        return;
      }
      case 'session_paused': {
        patchSessionStatus('paused');
        return;
      }
      default:
        return;
    }
  }

  function closeStream(): void {
    streamClosed = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function scheduleReconnect(): void {
    if (streamClosed || reconnectTimer !== null) return;
    const delay = Math.min(reconnectDelayMs, 10_000);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10_000);
      openStream();
    }, delay);
  }

  function openStream(): void {
    if (streamClosed || typeof window === 'undefined' || !sessionId) return;
    if (eventSource) return;
    const source = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/stream`);
    eventSource = source;
    const eventNames = [
      'brain_b_planned',
      'validator_scored',
      'concepts_extracted',
      'graph_delta',
      'turn_complete',
      'session_finished',
      'session_paused'
    ];
    for (const name of eventNames) {
      source.addEventListener(name, (evt) => {
        handleStreamEvent(name, (evt as MessageEvent).data);
      });
    }
    source.onopen = () => {
      reconnectDelayMs = 1000;
    };
    source.onerror = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      scheduleReconnect();
    };
  }

  onMount(async () => {
    try {
      bundle = await getJson<SessionBundleResponse>(`/sessions/${encodeURIComponent(sessionId)}`);
      if (bundle.session.turns.length === 0) {
        bundle = await postJson<SessionBundleResponse>(
          `/sessions/${encodeURIComponent(sessionId)}/start`,
          {}
        );
      }
      openStream();
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to load that session.';
    } finally {
      loading = false;
    }
  });

  onDestroy(() => {
    closeStream();
  });

  async function submitTurn(event: CustomEvent<{ content: string }>): Promise<void> {
    if (!bundle || isFinished || isPaused) {
      return;
    }

    sendPending = true;
    error = '';

    const optimisticTurn = {
      id: `pending-${Date.now()}`,
      session_id: bundle.session.id,
      role: 'participant',
      content: event.detail.content,
      index: bundle.session.turns.length,
      validation: null,
      brain_b_intent: null,
      get_user_input: null,
      retrieval_audit_id: null,
      created_at: new Date().toISOString()
    } as unknown as InterviewTurnRecord;
    bundle = {
      ...bundle,
      session: {
        ...bundle.session,
        turns: [...bundle.session.turns, optimisticTurn]
      }
    };

    try {
      bundle = await postJson<SessionBundleResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/turns`,
        {
          content: event.detail.content
        }
      );
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to send that turn right now.';
    } finally {
      sendPending = false;
    }
  }

  async function resumeSession(): Promise<void> {
    if (!bundle || !isPaused) {
      return;
    }

    resumePending = true;
    error = '';
    try {
      bundle = await postJson<SessionBundleResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/resume`,
        {}
      );
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to resume right now.';
    } finally {
      resumePending = false;
    }
  }
</script>

<svelte:head>
  <title>{chatCopy.page_title}</title>
</svelte:head>

{#if chatCopy.header_wordmark || chatCopy.header_eyebrow || chatCopy.header_subline}
  <header class="grid gap-1 pb-4">
    {#if chatCopy.header_wordmark}
      <p class="font-display text-[1.2rem] tracking-[0.14em] text-moss">
        {chatCopy.header_wordmark}
      </p>
    {/if}
    {#if chatCopy.header_eyebrow}
      <p class="eyebrow">{chatCopy.header_eyebrow}</p>
    {/if}
    {#if chatCopy.header_subline}
      <p class="text-sm text-[color:var(--muted)]">{chatCopy.header_subline}</p>
    {/if}
  </header>
{/if}

{#if loading}
  <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Loading session...</article>
{:else if !bundle}
  <article class="band px-6 py-6 text-sm text-ember">{error || 'Session not available.'}</article>
{:else}
  <section class="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_22rem]">
    <ChatPane
      title={bundle.campaign.title}
      messages={bundle.session.turns}
      agentName={bundle.campaign.outline.persona_hints.name ?? 'Mira'}
      participantName={bundle.session.identity_label || 'You'}
      placeholder={placeholderText}
      submitLabel={submitLabelText}
      disabled={isFinished}
      pending={sendPending}
      paused={isPaused}
      resumePending={resumePending}
      activePrompt={activePrompt}
      emptyState={chatCopy.empty_state}
      footerNote={footerNote}
      on:submit={submitTurn}
      on:resume={resumeSession}
    />

    <aside class="grid content-start gap-4">
      <section class="band grid gap-5 px-5 py-5">
        <div class="grid gap-1">
          <p class="eyebrow">{chatCopy.working_notes_eyebrow}</p>
          <p class="label">{chatCopy.working_notes_heading}</p>
        </div>

        <div class="grid gap-2">
          {#each rubricRows as row (row.key)}
            <div class="flex items-center gap-3" title={row.fullLabel}>
              <span class="w-8 font-mono text-xs text-[color:var(--muted)]">{row.key}</span>
              <span class="h-1.5 flex-1 overflow-hidden rounded-full bg-[color:rgba(232,224,207,0.08)]">
                {#if row.score > 0}
                  <span
                    class="block h-full rounded-full bg-[color:rgba(126,184,141,0.56)]"
                    style={`width:${Math.min(100, Math.max(0, row.score * 100))}%`}
                  ></span>
                {/if}
              </span>
              <span class="w-10 text-right font-mono text-xs text-[color:var(--muted)]">
                {row.score > 0 ? `${Math.round(row.score * 100)}%` : '—'}
              </span>
            </div>
          {/each}
        </div>

        {#if sendPending}
          <div class="flex items-center gap-2 px-1">
            <span class="dot-pulse"><span></span><span></span><span></span></span>
            <span class="text-xs text-[color:var(--muted)]">{chatCopy.agent_composing_label}</span>
          </div>
        {:else if latestAgentIntent?.retrieval_used}
          <div class="grid gap-1 rounded-[8px] border border-[color:rgba(126,184,141,0.36)] bg-[color:rgba(126,184,141,0.08)] px-3 py-2">
            <p class="label m-0 text-moss">{chatCopy.retrieved_heading}</p>
            <p class="m-0 text-xs leading-6 text-[color:var(--text)]">
              {retrievalMessage}
            </p>
          </div>
        {/if}

        <div class="grid gap-2">
          <p class="label">Questions Mira has captured so far</p>
          <p class="m-0 text-xs leading-6 text-[color:var(--muted)]">
            {satisfiedQuestionCountText}
          </p>
          {#if satisfiedQuestionPrompts.length > 0}
            <div class="grid max-h-44 gap-2 overflow-y-auto pr-1">
              {#each satisfiedQuestionPrompts as prompt}
                <p class="m-0 rounded-[8px] border border-[color:rgba(232,224,207,0.1)] bg-[color:rgba(232,224,207,0.03)] px-3 py-2 text-xs leading-5 text-[color:var(--text)]">
                  {prompt}
                </p>
              {/each}
            </div>
          {/if}
        </div>

        <p class="m-0 text-xs text-[color:var(--muted)]">
          {turnCounterText}
        </p>
      </section>

      <section class="band-soft grid gap-3 px-5 py-4">
        <p class="eyebrow">Session</p>
        <h2 class="font-display text-[1.5rem] leading-tight">{sessionTitle}</h2>
        <div class="flex flex-wrap items-center gap-3">
          <span class="status-badge" data-tone={statusTone}>{bundle.session.status}</span>
          <span class="text-xs text-[color:var(--muted)]">{attributionLabel}</span>
        </div>
      </section>

      {#if isFinished && closingTurn}
        <section class="info-banner grid gap-3">
          <div class="grid gap-1">
            <p class="eyebrow">{chatCopy.session_complete_eyebrow}</p>
            <p class="text-sm leading-7 text-[color:var(--text)]">{closingTurn.content}</p>
          </div>
          <div class="flex justify-end">
            <a class="button-secondary" href="/">{chatCopy.return_home_label}</a>
          </div>
        </section>
      {/if}

      {#if error}
        <section class="px-1 text-sm text-ember">{error}</section>
      {/if}
    </aside>
  </section>
{/if}

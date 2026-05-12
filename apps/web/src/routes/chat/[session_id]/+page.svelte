<script lang="ts">
  import { page } from '$app/stores';
  import { onDestroy, onMount, tick } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import ChatPane from '$lib/components/ChatPane.svelte';
  import { runtimeCopy } from '$lib/runtime-copy';
  import type {
    BrainBIntent,
    InterviewSessionRecord,
    InterviewTurnRecord,
    SessionBundleResponse,
    ValidationSnapshot
  } from '$lib/types';

  let bundle: SessionBundleResponse | null = null;
  let sessionId = '';
  let loading = true;
  let sendPending = false;
  let resumePending = false;
  let error = '';
  let endModalOpen = false;
  let endPending = false;
  let connected = true;
  let streamingAgentText = '';

  let modalCardEl: HTMLDivElement | null = null;
  let modalKeepBtnEl: HTMLButtonElement | null = null;
  let modalEndBtnEl: HTMLButtonElement | null = null;
  let lastFocusedBeforeModal: HTMLElement | null = null;
  let progressPanelOpen = false;
  let progressMediaQuery: MediaQueryList | null = null;

  interface InterviewAxisProgress {
    code: string;
    title: string;
    score: number;
    tone: 'moss' | 'brass' | 'neutral';
    stateLabel: string;
    isActive: boolean;
  }

  const axisOrder = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8'];
  const axisMatch = /^\s*(R\d+)\b/i;
  const axisLabelMatch = /^\s*(R\d+)\b\s*[—–:\-]\s*(.+)$/i;

  $: sessionId = $page.params.session_id ?? '';
  $: bundleChat = $page.data.runtimeContext?.ui.chat ?? null;
  $: chatCopy = {
    page_title: bundleChat?.page_title ?? runtimeCopy.chat.page_title,
    transcript_locked_label:
      bundleChat?.transcript_locked_label ?? runtimeCopy.chat.transcript_locked_label,
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
    submit_finished: bundleChat?.submit_finished ?? runtimeCopy.chat.submit_finished,
    thinking_messages:
      bundleChat?.thinking_messages && bundleChat.thinking_messages.length > 0
        ? bundleChat.thinking_messages
        : runtimeCopy.chat.thinking_messages
  };
  $: isFinished = bundle?.session.status === 'finished';
  $: isPaused = bundle?.session.status === 'paused';
  $: activePrompt = bundle && bundle.session.status === 'active'
    ? [...bundle.session.turns]
        .reverse()
        .find((turn) => turn.role === 'agent' && turn.get_user_input)?.get_user_input ?? null
    : null;
  $: latestAgentTurn = bundle
    ? [...bundle.session.turns].reverse().find((turn) => turn.role === 'agent') ?? null
    : null;
  $: closingTurn = bundle
    ? [...bundle.session.turns].reverse().find((turn) => turn.role === 'agent' && turn.validation?.closing) ??
      latestAgentTurn
    : null;
  $: attributionLabel = bundle
    ? bundle.session.consent_mode === 'anonymous'
      ? 'Anonymous'
      : `Attributed as ${bundle.session.identity_label || 'participant'}`
    : '';
  $: activePlan = bundle?.session.next_plan ?? null;
  $: visiblePlan = activePlan ?? latestAgentTurn?.brain_b_intent ?? null;
  $: activeAxisCode = extractAxisCode(visiblePlan?.active_axis ?? null);
  $: interviewAxes = buildInterviewAxes(bundle, visiblePlan);
  $: coveredAxisCount = interviewAxes.filter((axis) => axis.score >= 0.8).length;
  $: openedAxisCount = interviewAxes.filter((axis) => axis.score > 0).length;
  $: activeAxisTitle =
    activeAxisCode
      ? interviewAxes.find((axis) => axis.code === activeAxisCode)?.title ??
        activeAxisCode
      : null;
  $: runningTurnCount = bundle?.session.turns.filter((turn) => turn.role === 'participant').length ?? 0;
  $: progressSummary = isFinished
    ? 'This session is complete. Mira has closed the interview.'
    : runningTurnCount > 0
      ? `Mira has opened ${openedAxisCount} of ${axisOrder.length} research threads and is grounding each turn.`
      : 'Mira is ready to begin your guided interview.';
  $: statusTone = bundle
    ? bundle.session.status === 'active'
      ? 'moss'
      : bundle.session.status === 'paused'
        ? 'brass'
        : 'neutral'
    : 'neutral';
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

  let eventSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelayMs = 1000;
  let streamClosed = false;
  let disconnectGraceTimer: ReturnType<typeof setTimeout> | null = null;

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

  function extractAxisCode(raw: string | null): string | null {
    const match = raw?.match(axisMatch) ?? null;
    return match ? match[1].toUpperCase() : null;
  }

  function extractAxisTitle(raw: string | null, fallback: string): string {
    if (!raw) return fallback;
    const match = raw.match(axisLabelMatch);
    if (match && match[2]) {
      return match[2].trim();
    }
    return raw.trim().replace(/^\s*R\d+\s*[—–:\-]?\s*/, '') || fallback;
  }

  function clampAxisScore(raw: number | undefined | null): number {
    if (typeof raw !== 'number' || Number.isNaN(raw)) return 0;
    return Math.max(0, Math.min(1, raw));
  }

  function axisToneForScore(score: number): 'moss' | 'brass' | 'neutral' {
    if (score >= 0.9) return 'moss';
    if (score >= 0.4) return 'brass';
    return 'neutral';
  }

  function axisStateLabel(score: number): string {
    if (score >= 0.9) return 'covered';
    if (score >= 0.4) return 'developing';
    if (score > 0) return 'started';
    return 'not started';
  }

  function buildInterviewAxes(
    sessionBundle: SessionBundleResponse | null,
    intent: BrainBIntent | null
  ): InterviewAxisProgress[] {
    if (!sessionBundle) return [];

    const coverageByCode = new Map<string, { score: number; rawAxis: string }>();
    for (const entry of intent?.axes_coverage ?? []) {
      const code = extractAxisCode(entry.axis);
      if (!code) continue;
      coverageByCode.set(code, {
        score: clampAxisScore(entry.score),
        rawAxis: entry.axis
      });
    }

    const rubricTitles = new Map<string, string>();
    for (const dimension of sessionBundle.campaign.outline.rubric.coverage_dimensions ?? []) {
      const code = extractAxisCode(dimension);
      if (!code || !/^R\d+$/.test(code) || !axisOrder.includes(code)) continue;
      if (!rubricTitles.has(code)) {
        rubricTitles.set(code, extractAxisTitle(dimension, code));
      }
    }

    return axisOrder.map((code, index) => {
      const coverage = coverageByCode.get(code);
      const score = coverage?.score ?? 0;
      const fallback = coverage?.rawAxis || `${code} — ${rubricTitles.get(code) ?? `Research thread ${index + 1}`}`;
      return {
        code,
        title: rubricTitles.get(code) ?? extractAxisTitle(fallback, `Research thread ${index + 1}`),
        score,
        tone: axisToneForScore(score),
        stateLabel: axisStateLabel(score),
        isActive: code === activeAxisCode
      };
    });
  }

  function syncProgressPanelState(): void {
    if (typeof window === 'undefined') return;
    progressPanelOpen = window.matchMedia('(min-width: 768px)').matches;
  }

  function handleStreamEvent(name: string, raw: string): void {
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    switch (name) {
      case 'token': {
        const text = typeof data.text === 'string' ? data.text : '';
        if (text && sendPending) {
          streamingAgentText = `${streamingAgentText}${text}`;
        }
        return;
      }
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

  function clearDisconnectGrace(): void {
    if (disconnectGraceTimer !== null) {
      clearTimeout(disconnectGraceTimer);
      disconnectGraceTimer = null;
    }
  }

  function startDisconnectGrace(): void {
    if (disconnectGraceTimer !== null) return;
    disconnectGraceTimer = setTimeout(() => {
      connected = false;
      disconnectGraceTimer = null;
    }, 3000);
  }

  function closeStream(): void {
    streamClosed = true;
    clearDisconnectGrace();
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
      'token',
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
      clearDisconnectGrace();
      connected = true;
    };
    source.onerror = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      startDisconnectGrace();
      scheduleReconnect();
    };
  }

  onMount(async () => {
    syncProgressPanelState();
    progressMediaQuery = window.matchMedia('(min-width: 768px)');
    progressMediaQuery.addEventListener('change', syncProgressPanelState);

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
    if (progressMediaQuery) {
      progressMediaQuery.removeEventListener('change', syncProgressPanelState);
    }
  });

  function rollbackOptimisticTurn(turnId: string): void {
    if (!bundle) return;
    bundle = {
      ...bundle,
      session: {
        ...bundle.session,
        turns: bundle.session.turns.filter((turn) => turn.id !== turnId)
      }
    };
  }

  async function submitTurn(event: CustomEvent<{ content: string }>): Promise<void> {
    if (!bundle || isFinished || isPaused) {
      return;
    }

    if (event.detail.content.trim() === 'End interview') {
      await finishSession();
      return;
    }

    sendPending = true;
    streamingAgentText = '';
    error = '';

    const optimisticTurnId = `pending-${Date.now()}`;
    const optimisticTurn = {
      id: optimisticTurnId,
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
      streamingAgentText = '';
    } catch (caught) {
      rollbackOptimisticTurn(optimisticTurnId);
      streamingAgentText = '';
      error = caught instanceof ApiError ? caught.message : 'Unable to send that turn right now.';
    } finally {
      sendPending = false;
    }
  }

  async function finishSession(): Promise<void> {
    if (!bundle || isFinished) {
      return;
    }
    endPending = true;
    error = '';
    try {
      const finishedSession = await postJson<InterviewSessionRecord>(
        `/sessions/${encodeURIComponent(sessionId)}/finish`,
        {}
      );
      bundle = {
        ...bundle,
        session: { ...bundle.session, ...finishedSession }
      };
      endModalOpen = false;
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to end the conversation right now.';
    } finally {
      endPending = false;
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

  async function openEndModal(): Promise<void> {
    if (isFinished || endPending) {
      return;
    }
    if (typeof document !== 'undefined') {
      lastFocusedBeforeModal = document.activeElement as HTMLElement | null;
    }
    endModalOpen = true;
    await tick();
    modalKeepBtnEl?.focus();
  }

  function closeEndModal(): void {
    if (endPending) {
      return;
    }
    endModalOpen = false;
    if (lastFocusedBeforeModal) {
      lastFocusedBeforeModal.focus();
      lastFocusedBeforeModal = null;
    }
  }

  function focusableInModal(): HTMLElement[] {
    if (!modalCardEl) return [];
    const selector =
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.from(modalCardEl.querySelectorAll<HTMLElement>(selector));
  }

  function handleModalKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeEndModal();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusableInModal();
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey) {
      if (active === first || !modalCardEl?.contains(active)) {
        event.preventDefault();
        last.focus();
      }
    } else {
      if (active === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }
</script>

<svelte:head>
  <title>{chatCopy.page_title}</title>
</svelte:head>

{#if loading}
  <article class="chat-shell-message">Loading session...</article>
{:else if !bundle}
  <article class="chat-shell-message chat-shell-message--error">{error || 'Session not available.'}</article>
{:else}
  <section class="chat-grid">
    <ChatPane
      title={bundle.campaign.title}
      messages={bundle.session.turns}
      agentName={bundle.campaign.outline.persona_hints.name ?? 'Mira'}
      participantName={bundle.session.identity_label || 'You'}
      placeholder={placeholderText}
      submitLabel={submitLabelText}
      disabled={isFinished}
      pending={sendPending}
      streamingAgentText={streamingAgentText}
      paused={isPaused}
      resumePending={resumePending}
      activePrompt={activePrompt}
      emptyState={chatCopy.empty_state}
      footerNote={footerNote}
      connected={connected}
      thinkingMessages={chatCopy.thinking_messages}
      on:submit={submitTurn}
      on:resume={resumeSession}
      on:end={openEndModal}
    />

    <aside class="chat-aside">
      <section class="interview-progress">
        <p class="eyebrow">Mira progress</p>
        <p class="interview-progress-copy">{progressSummary}</p>

        {#if activeAxisTitle}
          <p class="interview-progress-current">
            Mira is actively exploring
            <span class="status-badge" data-tone="moss">{activeAxisTitle}</span>
            .
          </p>
        {:else if runningTurnCount > 0}
          <p class="interview-progress-current">
            Mira is mapping this session thread by thread.
          </p>
        {:else}
          <p class="interview-progress-current">Mira is ready to begin with your first grounded prompt.</p>
        {/if}

        <p class="interview-progress-meta">
          <span class="status-badge" data-tone="neutral">Answer {runningTurnCount}</span>
          <span>{openedAxisCount} / {axisOrder.length} threads opened</span>
        </p>

        <details
          class="interview-progress-drawer"
          bind:open={progressPanelOpen}
        >
          <summary class="interview-progress-summary">
            R1–R8 coverage rail
            <span class="interview-progress-summary-subtle">
              {coveredAxisCount} at depth
            </span>
          </summary>
          <div class="interview-progress-body">
            {#if interviewAxes.length === 0}
              <p class="interview-progress-empty">
                Mira will surface this as grounded coverage updates arrive.
              </p>
            {:else}
              {#each interviewAxes as axis}
                <article class="interview-axis" class:interview-axis--active={axis.isActive}>
                  <div class="interview-axis-head">
                    <p class="interview-axis-label">
                      <span class="interview-axis-code" data-tone={axis.tone}>{axis.code}</span>
                      <span class="interview-axis-title">{axis.title}</span>
                    </p>
                    <p class="interview-axis-state">
                      {axis.stateLabel}
                    </p>
                  </div>
                  <div class="interview-axis-meter-wrap" aria-hidden="true">
                    <span
                      class="interview-axis-meter"
                    >
                      <span
                        class="interview-axis-meter-fill"
                        class:interview-axis-meter-fill--moss={axis.tone === 'moss'}
                        class:interview-axis-meter-fill--brass={axis.tone === 'brass'}
                        style={`--axis-score:${Math.round(axis.score * 100)}%`}
                      ></span>
                    </span>
                    <span class="interview-axis-score">{Math.round(axis.score * 100)}%</span>
                  </div>
                </article>
              {/each}
            {/if}
          </div>
        </details>
      </section>

      <p class="session-meta">
        {#if bundle.session.status !== 'active'}
          <span class="status-badge" data-tone={statusTone}>{bundle.session.status}</span>
        {/if}
        <span>{attributionLabel}</span>
      </p>

      {#if isFinished && closingTurn}
        <section class="closing-card">
          <p class="eyebrow">{chatCopy.session_complete_eyebrow}</p>
          <p class="closing-card-body">{closingTurn.content}</p>
          <a class="button-secondary closing-card-cta" href="/">{chatCopy.return_home_label}</a>
        </section>
      {/if}

      {#if error}
        <p class="chat-error" role="alert">{error}</p>
      {/if}
    </aside>
  </section>

  {#if endModalOpen}
    <div
      class="modal-backdrop"
      role="presentation"
      tabindex="-1"
      on:click={closeEndModal}
    >
      <div
        bind:this={modalCardEl}
        class="modal-card"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="end-modal-title"
        aria-describedby="end-modal-body"
        tabindex="-1"
        on:click|stopPropagation
        on:keydown={handleModalKeydown}
      >
        <p class="eyebrow">End interview</p>
        <h2 id="end-modal-title" class="modal-title">Close this session?</h2>
        <p id="end-modal-body" class="modal-body">
          This will close the interview and stop follow-up questions.
          You can still revisit this URL to read what was recorded.
        </p>
        <div class="modal-actions">
          <button
            bind:this={modalKeepBtnEl}
            type="button"
            class="button-secondary"
            disabled={endPending}
            on:click={closeEndModal}
          >
            Keep talking
          </button>
          <button
            bind:this={modalEndBtnEl}
            type="button"
            class="button-danger"
            disabled={endPending}
            on:click={finishSession}
          >
            {#if endPending}
              <span class="dot-pulse" aria-hidden="true"><span></span><span></span><span></span></span>
              <span>Closing</span>
            {:else}
              <span>End interview</span>
            {/if}
          </button>
        </div>
      </div>
    </div>
  {/if}
{/if}

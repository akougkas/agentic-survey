<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import ChatPane from '$lib/components/ChatPane.svelte';
  import { demoCopy } from '$lib/demo-copy';
  import type { InterviewTurnRecord, SessionBundleResponse } from '$lib/types';

  let bundle: SessionBundleResponse | null = null;
  let sessionId = '';
  let loading = true;
  let sendPending = false;
  let resumePending = false;
  let error = '';

  $: sessionId = $page.params.session_id ?? '';
  $: bundleChat = $page.data.runtimeContext?.ui.chat ?? null;
  $: chatCopy = {
    header_eyebrow: bundleChat?.header_eyebrow ?? demoCopy.chat.header_eyebrow,
    header_wordmark: bundleChat?.header_wordmark ?? demoCopy.chat.header_wordmark,
    header_subline: bundleChat?.header_subline ?? demoCopy.chat.header_subline,
    page_title: bundleChat?.page_title ?? demoCopy.chat.page_title,
    conversation_heading: bundleChat?.conversation_heading ?? demoCopy.chat.conversation_heading,
    transcript_locked_label:
      bundleChat?.transcript_locked_label ?? demoCopy.chat.transcript_locked_label,
    agent_composing_label: bundleChat?.agent_composing_label ?? demoCopy.chat.agent_composing_label,
    working_notes_eyebrow: bundleChat?.working_notes_eyebrow ?? demoCopy.chat.working_notes_eyebrow,
    working_notes_heading: bundleChat?.working_notes_heading ?? demoCopy.chat.working_notes_heading,
    retrieved_heading: bundleChat?.retrieved_heading ?? demoCopy.chat.retrieved_heading,
    retrieved_description_singular:
      bundleChat?.retrieved_description_singular ?? demoCopy.chat.retrieved_description_singular,
    retrieved_description_plural:
      bundleChat?.retrieved_description_plural ?? demoCopy.chat.retrieved_description_plural,
    concepts_heading: bundleChat?.concepts_heading ?? demoCopy.chat.concepts_heading,
    concepts_empty: bundleChat?.concepts_empty ?? demoCopy.chat.concepts_empty,
    turn_counter_template: bundleChat?.turn_counter_template ?? demoCopy.chat.turn_counter_template,
    active_footer: bundleChat?.active_footer ?? demoCopy.chat.active_footer,
    paused_footer: bundleChat?.paused_footer ?? demoCopy.chat.paused_footer,
    finished_footer: bundleChat?.finished_footer ?? demoCopy.chat.finished_footer,
    session_complete_eyebrow:
      bundleChat?.session_complete_eyebrow ?? demoCopy.chat.session_complete_eyebrow,
    return_home_label: bundleChat?.return_home_label ?? demoCopy.chat.return_home_label,
    empty_state: bundleChat?.empty_state ?? demoCopy.chat.empty_state,
    placeholder_default: bundleChat?.placeholder_default ?? demoCopy.chat.placeholder_default,
    placeholder_with_chips:
      bundleChat?.placeholder_with_chips ?? demoCopy.chat.placeholder_with_chips,
    submit_idle: bundleChat?.submit_idle ?? demoCopy.chat.submit_idle,
    submit_pending: bundleChat?.submit_pending ?? demoCopy.chat.submit_pending,
    submit_finished: bundleChat?.submit_finished ?? demoCopy.chat.submit_finished
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
    ? coverageByAxis(bundle.session.turns, bundle.campaign.outline.axes ?? [])
    : coverageByAxis([], []);
  $: emergingConcepts = bundle ? collectConcepts(bundle.session.turns) : [];
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
    outlineAxes: string[]
  ): Array<{ key: string; score: number; fullLabel: string }> {
    const latest = [...turns]
      .reverse()
      .find((t) => t.role === 'agent' && t.brain_b_intent?.axes_coverage);
    const coverageList = latest?.brain_b_intent?.axes_coverage ?? [];

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

  function collectConcepts(
    turns: InterviewTurnRecord[]
  ): Array<{ label: string; isLatest: boolean }> {
    const participantTurns = turns.filter((t) => t.role === 'participant');
    if (participantTurns.length === 0) return [];
    const latest = participantTurns[participantTurns.length - 1];
    const latestKeys = new Set(
      (latest.validation?.extracted_concepts ?? []).map((c) => c.label.toLowerCase())
    );
    const seen = new Set<string>();
    const out: Array<{ label: string; isLatest: boolean }> = [];
    for (let i = participantTurns.length - 1; i >= 0; i -= 1) {
      const list = participantTurns[i].validation?.extracted_concepts ?? [];
      for (const concept of list) {
        const key = concept.label.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ label: concept.label, isLatest: latestKeys.has(key) });
        if (out.length >= 10) return out;
      }
    }
    return out;
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
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to load that session.';
    } finally {
      loading = false;
    }
  });

  async function submitTurn(event: CustomEvent<{ content: string }>): Promise<void> {
    if (!bundle || isFinished || isPaused) {
      return;
    }

    sendPending = true;
    error = '';

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
          <p class="label">{chatCopy.concepts_heading}</p>
          {#if emergingConcepts.length === 0}
            <p class="m-0 text-xs leading-6 text-[color:var(--muted)]">
              {chatCopy.concepts_empty}
            </p>
          {:else}
            <div class="flex flex-wrap gap-2">
              {#each emergingConcepts as concept}
                <span class="status-badge" data-tone={concept.isLatest ? 'moss' : 'neutral'}>
                  {concept.label}
                </span>
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

<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import ChatPane from '$lib/components/ChatPane.svelte';
  import { demoCopy } from '$lib/demo-copy';
  import type { SessionBundleResponse } from '$lib/types';

  let bundle: SessionBundleResponse | null = null;
  let sessionId = '';
  let loading = true;
  let sendPending = false;
  let resumePending = false;
  let error = '';

  $: sessionId = $page.params.session_id ?? '';
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
  $: lastValidation = bundle
    ? [...bundle.session.turns]
        .reverse()
        .find(
          (turn) =>
            turn.role === 'participant' &&
            turn.validation &&
            !turn.validation.closing &&
            typeof turn.validation.coverage_score === 'number'
        )?.validation ?? null
    : null;

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
      placeholder={isFinished ? 'This session is complete.' : isPaused ? 'Resume the session to continue.' : 'Answer in your own words.'}
      submitLabel={isFinished ? 'Session complete' : 'Send'}
      disabled={isFinished}
      pending={sendPending}
      paused={isPaused}
      resumePending={resumePending}
      activePrompt={activePrompt}
      footerNote={isFinished
        ? demoCopy.chat.finishedFooter
        : isPaused
          ? 'Mira has paused this session. Resume when you want to keep going.'
          : demoCopy.chat.activeFooter}
      on:submit={submitTurn}
      on:resume={resumeSession}
    />

    <aside class="grid content-start gap-4">
      {#if isFinished && closingTurn}
        <section class="info-banner grid gap-3">
          <div class="grid gap-1">
            <p class="eyebrow">Session complete</p>
            <p class="text-sm leading-7 text-[color:var(--text)]">{closingTurn.content}</p>
          </div>
          <a class="text-sm text-moss" href="/">Back to home</a>
        </section>
      {/if}

      <section class="band grid gap-5 px-6 py-6">
        <div class="grid gap-2">
          <p class="eyebrow">Session</p>
          <h2 class="section-title text-[1.8rem] md:text-[2rem]">{bundle.campaign.title}</h2>
          <p class="section-copy">
            {bundle.session.consent_mode === 'named' && bundle.session.identity_label
              ? `Quoted as ${bundle.session.identity_label}.`
              : demoCopy.chat.anonymousParticipant}
          </p>
        </div>

        <dl class="grid gap-4 border-t border-[color:var(--line)] pt-4">
          <div class="grid gap-1">
            <dt class="label">Status</dt>
            <dd class="m-0 text-sm text-[color:var(--text)]">{bundle.session.status}</dd>
          </div>
          {#if bundle.session.close_reason}
            <div class="grid gap-1">
              <dt class="label">Close reason</dt>
              <dd class="m-0 text-sm text-[color:var(--text)]">{bundle.session.close_reason}</dd>
            </div>
          {/if}
          {#if bundle.session.paused_reason}
            <div class="grid gap-1">
              <dt class="label">Paused reason</dt>
              <dd class="m-0 text-sm text-[color:var(--text)]">{bundle.session.paused_reason}</dd>
            </div>
          {/if}
          <div class="grid gap-1">
            <dt class="label">Pinned endpoint</dt>
            <dd class="m-0 text-sm text-[color:var(--text)]">{bundle.session.pinned_endpoint}</dd>
          </div>
          <div class="grid gap-1">
            <dt class="label">Turns</dt>
            <dd class="m-0 text-sm text-[color:var(--text)]">{bundle.session.turns.length}</dd>
          </div>
        </dl>
      </section>

      {#if lastValidation}
        <section class="band-soft grid gap-3 px-5 py-5">
          <p class="eyebrow">Latest signal</p>
          <p class="m-0 text-sm text-[color:var(--text)]">
            Coverage {Math.round((lastValidation.coverage_score ?? 0) * 100)}% · Quality
            {Math.round((lastValidation.quality_score ?? 0) * 100)}%
          </p>
          {#if lastValidation.objective_tags?.length}
            <p class="m-0 text-sm text-[color:var(--muted)]">
              Tagged to {lastValidation.objective_tags.length} objective{lastValidation.objective_tags.length === 1 ? '' : 's'}.
            </p>
          {/if}
          {#if lastValidation.extracted_concepts?.length}
            <div class="flex flex-wrap gap-2">
              {#each lastValidation.extracted_concepts as concept}
                <span
                  class="rounded-[8px] bg-[color:rgba(232,224,207,0.05)] px-3 py-1 text-xs text-[color:var(--muted)]"
                >
                  {concept.label}
                </span>
              {/each}
            </div>
          {/if}
        </section>
      {/if}

      {#if error}
        <section class="px-1 text-sm text-ember">{error}</section>
      {/if}
    </aside>
  </section>
{/if}

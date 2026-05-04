<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, getText, postJson } from '$lib/api';
  import { getAdminSession } from '$lib/admin';
  import type {
    MethodObservation,
    MethodObservationCreate,
    QuestionAnswerRow,
    QuestionCoverageStatus,
    SessionBundleResponse
  } from '$lib/types';

  let bundle: SessionBundleResponse | null = null;
  let questionRows: QuestionAnswerRow[] = [];
  let methodObservations: MethodObservation[] = [];
  let observationBody = '';
  let observationTags = '';
  let observationError = '';
  let observationPending = false;
  let observationsLoading = false;
  let loading = true;
  let error = '';

  $: campaignId = $page.params.id ?? '';
  $: sessionId = $page.params.session_id ?? '';
  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;
  $: sessionQuestionRows = questionRows.filter((row) => row.session_id === sessionId);
  $: questionGroups = groupQuestionRows(sessionQuestionRows);
  $: observationsNewest = [...methodObservations].sort((left, right) => {
    const byTime = Date.parse(right.created_at) - Date.parse(left.created_at);
    return byTime || right.id.localeCompare(left.id);
  });

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      const [sessionBundle, answersJsonl] = await Promise.all([
        getJson<SessionBundleResponse>(`/sessions/${encodeURIComponent(sessionId)}`),
        getText(`/admin/campaigns/${encodeURIComponent(campaignId)}/answers.jsonl`)
      ]);
      bundle = sessionBundle;
      questionRows = parseQuestionRows(answersJsonl);
      observationsLoading = true;
      try {
        const observationBundle = await getJson<{ observations: MethodObservation[] }>(
          `/admin/campaigns/${encodeURIComponent(campaignId)}/sessions/${encodeURIComponent(sessionId)}/observations`
        );
        methodObservations = observationBundle.observations;
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) {
          await goto(loginPath);
          return;
        }
        observationError = caught instanceof ApiError ? caught.message : 'Unable to load observations.';
      } finally {
        observationsLoading = false;
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to load the session.';
    } finally {
      loading = false;
    }
  });

  async function submitMethodObservation(): Promise<void> {
    const body = observationBody.trim();
    if (!body) {
      observationError = 'Observation body is required.';
      return;
    }

    observationPending = true;
    observationError = '';
    const payload: MethodObservationCreate = {
      body,
      tags: parseTags(observationTags)
    };
    try {
      const created = await postJson<MethodObservation>(
        `/admin/campaigns/${encodeURIComponent(campaignId)}/sessions/${encodeURIComponent(sessionId)}/observations`,
        payload
      );
      methodObservations = [created, ...methodObservations.filter((observation) => observation.id !== created.id)];
      observationBody = '';
      observationTags = '';
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      observationError = caught instanceof ApiError ? caught.message : 'Unable to add observation.';
    } finally {
      observationPending = false;
    }
  }

  function parseTags(raw: string): string[] {
    const seen = new Set<string>();
    const tags: string[] = [];
    for (const part of raw.split(',')) {
      const tag = part.trim().toLowerCase();
      if (!tag || seen.has(tag)) continue;
      tags.push(tag);
      seen.add(tag);
    }
    return tags;
  }

  function parseQuestionRows(raw: string): QuestionAnswerRow[] {
    return raw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parsed = JSON.parse(line) as QuestionAnswerRow;
        return {
          ...parsed,
          confidence: Number(parsed.confidence ?? 0)
        };
      });
  }

  function groupQuestionRows(rows: QuestionAnswerRow[]): Array<{ tier: string; rows: QuestionAnswerRow[] }> {
    const orderedTiers = ['A', 'B', 'C', 'X'];
    const tierSet = new Set([...orderedTiers, ...rows.map((row) => row.tier || 'Other')]);
    return [...tierSet]
      .map((tier) => ({
        tier,
        rows: rows.filter((row) => (row.tier || 'Other') === tier)
      }))
      .filter((group) => group.rows.length > 0);
  }

  function questionStatusTone(status: QuestionCoverageStatus): 'neutral' | 'brass' | 'moss' | 'ember' {
    if (status === 'satisfied') return 'moss';
    if (status === 'skipped') return 'ember';
    if (status === 'targeting' || status === 'partial') return 'brass';
    return 'neutral';
  }

  function truncate(text: string, max = 120): string {
    if (!text) return '';
    const clean = text.replace(/\s+/g, ' ').trim();
    return clean.length <= max ? clean : `${clean.slice(0, max - 1).trimEnd()}…`;
  }

  function formatDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      throw new Error(`Invalid timestamp: ${value}`);
    }
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(date);
  }
</script>

<section class="grid gap-5">
  <a class="text-sm text-moss" href={`/admin/campaigns/${campaignId}`}>&larr; Back to campaign</a>

  {#if loading}
    <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Loading transcript...</article>
  {:else if error || !bundle}
    <article class="band px-6 py-6 text-sm text-ember">{error || 'Session not found.'}</article>
  {:else}
    <section class="band grid gap-5 px-6 py-6">
      <div class="grid gap-2">
        <p class="eyebrow">{bundle.campaign.title}</p>
        <h2 class="section-title">Session transcript</h2>
        <p class="section-copy">
          {bundle.session.consent_mode}{bundle.session.identity_label ? ` · ${bundle.session.identity_label}` : ''} ·
          pinned {bundle.session.pinned_endpoint} · status {bundle.session.status}
        </p>
      </div>

      <div class="stack-list">
        {#each bundle.session.turns as turn}
          <article
            id={`turn-${turn.id}`}
            class={`stack-row ${
              turn.validation?.closing
                ? 'bg-[color:rgba(126,184,141,0.08)]'
                : turn.role === 'agent'
                  ? 'bg-[color:rgba(126,184,141,0.03)]'
                  : 'bg-transparent'
            }`}
          >
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex flex-wrap items-center gap-2">
                <p class="label m-0">
                  {turn.role === 'agent' ? 'Mira' : bundle.session.identity_label || 'Participant'}
                </p>
                {#if turn.validation?.closing}
                  <span
                    class="rounded-[8px] bg-[color:rgba(126,184,141,0.16)] px-2 py-1 text-[11px] uppercase tracking-[0.14em] text-moss"
                  >
                    Closing summary
                  </span>
                {/if}
              </div>
              <p class="label m-0">Turn {turn.index + 1}</p>
            </div>

            <p class="m-0 max-w-4xl text-sm leading-7 text-[color:var(--text)]">{turn.content}</p>

            {#if turn.validation && !turn.validation.closing && typeof turn.validation.coverage_score === 'number'}
              <p class="m-0 text-xs text-[color:var(--muted)]">
                coverage {Math.round((turn.validation.coverage_score ?? 0) * 100)}% · quality
                {Math.round((turn.validation.quality_score ?? 0) * 100)}%
                {turn.validation.follow_up_needed ? ' · follow-up flagged' : ''}
              </p>
            {/if}
          </article>
        {/each}
      </div>
    </section>

    <section class="band grid gap-5 px-6 py-6">
      <div class="grid gap-2">
        <p class="eyebrow">Method observations</p>
        <h2 class="section-title">Operator notes for this session</h2>
      </div>

      <form class="grid gap-3" on:submit|preventDefault={submitMethodObservation}>
        <textarea
          bind:value={observationBody}
          class="field min-h-[128px] resize-y"
          maxlength="4000"
          placeholder="What changed in the interview method?"
        ></textarea>
        <div class="grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            type="text"
            bind:value={observationTags}
            class="field"
            placeholder="Tags"
          />
          <button class="button-primary" disabled={observationPending || !observationBody.trim()}>
            {observationPending ? 'Adding...' : 'Add observation'}
          </button>
        </div>
      </form>

      {#if observationError}
        <p
          class="m-0 rounded-[8px] border border-[color:rgba(185,93,68,0.35)] bg-[color:rgba(185,93,68,0.08)] px-3 py-2 text-sm text-ember"
        >
          {observationError}
        </p>
      {/if}

      {#if observationsLoading}
        <p class="m-0 text-sm text-[color:var(--muted)]">Loading observations...</p>
      {:else if observationsNewest.length === 0}
        <p class="m-0 text-sm text-[color:var(--muted)]">No method observations yet.</p>
      {:else}
        <div class="stack-list">
          {#each observationsNewest as observation}
            <article class="stack-row">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <p class="label m-0">{observation.author}</p>
                <p class="label m-0">{formatDate(observation.created_at)}</p>
              </div>
              <p class="m-0 max-w-4xl whitespace-pre-wrap text-sm leading-7 text-[color:var(--text)]">
                {observation.body}
              </p>
              {#if observation.tags.length > 0}
                <div class="flex flex-wrap gap-2">
                  {#each observation.tags as tag}
                    <span
                      class="rounded-[8px] border border-[color:var(--line)] bg-[color:rgba(217,210,190,0.08)] px-2 py-1 text-[11px] uppercase text-[color:var(--muted)]"
                    >
                      {tag}
                    </span>
                  {/each}
                </div>
              {/if}
            </article>
          {/each}
        </div>
      {/if}
    </section>

    <section class="band grid gap-5 px-6 py-6">
      <div class="grid gap-2">
        <p class="eyebrow">Question coverage</p>
        <h2 class="section-title">Questions covered in this session</h2>
      </div>

      {#if questionGroups.length === 0}
        <p class="m-0 text-sm text-[color:var(--muted)]">
          No eligible question bank rows for this session.
        </p>
      {:else}
        <div class="grid gap-5">
          {#each questionGroups as group}
            <section class="grid gap-3">
              <div class="flex items-center gap-3">
                <span class="status-badge" data-tone="neutral">Tier {group.tier}</span>
                <span class="text-xs text-[color:var(--muted)]">{group.rows.length} questions</span>
              </div>
              <div class="stack-list">
                {#each group.rows as row}
                  <article class="stack-row">
                    <div class="flex flex-wrap items-center justify-between gap-3">
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="status-badge" data-tone={questionStatusTone(row.status)}>
                          {row.status}
                        </span>
                        <p class="label m-0">{row.question_id} · Tier {row.tier || 'Other'}</p>
                      </div>
                      <p class="label m-0">{Math.round(row.confidence * 100)}%</p>
                    </div>
                    <p class="m-0 max-w-4xl text-sm leading-7 text-[color:var(--text)]">
                      {truncate(row.prompt)}
                    </p>
                    {#if row.evidence_quote}
                      <p class="m-0 max-w-4xl text-xs italic leading-6 text-[color:var(--muted)]">
                        "{row.evidence_quote}"
                      </p>
                    {/if}
                    {#if row.turn_id}
                      <a class="text-xs text-moss" href={`#turn-${row.turn_id}`}>
                        Source turn
                      </a>
                    {/if}
                  </article>
                {/each}
              </div>
            </section>
          {/each}
        </div>
      {/if}
    </section>
  {/if}
</section>

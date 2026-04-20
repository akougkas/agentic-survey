<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson } from '$lib/api';
  import { getAdminSession } from '$lib/admin';
  import type { SessionBundleResponse } from '$lib/types';

  let bundle: SessionBundleResponse | null = null;
  let loading = true;
  let error = '';

  $: campaignId = $page.params.id ?? '';
  $: sessionId = $page.params.session_id ?? '';
  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      bundle = await getJson<SessionBundleResponse>(`/sessions/${encodeURIComponent(sessionId)}`);
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
  {/if}
</section>

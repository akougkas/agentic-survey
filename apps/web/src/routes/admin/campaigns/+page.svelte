<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import { campaignActivityLabel, campaignSourceLabel, campaignStateLabel, campaignStateTone } from '$lib/campaign-ui';
  import { getAdminSession } from '$lib/admin';
  import { runtimeCopy } from '$lib/runtime-copy';
  import type { Campaign, CampaignOverviewItem, CampaignOverviewResponse } from '$lib/types';

  let overview: CampaignOverviewResponse | null = null;
  let loading = true;
  let error = '';
  let seedPending = '';

  $: runtimeContext = $page.data.runtimeContext ?? null;
  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      await loadOverview();
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to load the workspace.';
      loading = false;
    }
  });

  async function loadOverview(): Promise<void> {
    loading = true;
    error = '';
    try {
      overview = await getJson<CampaignOverviewResponse>('/campaigns/overview');
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to load campaign overview.';
    } finally {
      loading = false;
    }
  }

  async function createFromSeed(seedSlug: string): Promise<void> {
    seedPending = seedSlug;
    error = '';
    try {
      const campaign = await postJson<Campaign>('/campaigns/from-seed', {
        seed_slug: seedSlug,
      });
      await goto(`/admin/campaigns/${campaign.id}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to start that seeded campaign.';
    } finally {
      seedPending = '';
    }
  }

  function reviewSummary(item: CampaignOverviewItem): string {
    if (item.latest_outline_revision?.summary) return item.latest_outline_revision.summary;
    if (item.campaign.source === 'seed') return runtimeCopy.campaigns.seededReadyMessage;
    return runtimeCopy.campaigns.noSummaryYet;
  }
</script>

{#if loading}
  <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Loading workspace...</article>
{:else if error && !overview}
  <article class="band px-6 py-6 text-sm text-ember">{error}</article>
{:else if overview}
  <section class="grid gap-6">
    <article class="band grid gap-5 px-6 py-7 md:px-8">
      <div class="grid gap-3">
        <p class="eyebrow">{runtimeCopy.campaigns.overviewEyebrow}</p>
        <h2 class="section-title md:text-[2.8rem]">{runtimeCopy.campaigns.overviewTitle}</h2>
        <p class="section-copy">{runtimeCopy.campaigns.overviewDescription}</p>
      </div>

      <div class="metric-grid border-t border-[color:var(--line)] pt-5">
        <article class="metric-card">
          <p class="label m-0">{runtimeCopy.campaigns.totalCampaignsLabel}</p>
          <p class="m-0 font-display text-[2rem] leading-none">{overview.summary.total_campaigns}</p>
        </article>
        <article class="metric-card">
          <p class="label m-0">{runtimeCopy.campaigns.reviewReadyLabel}</p>
          <p class="m-0 font-display text-[2rem] leading-none">{overview.summary.review_ready_count}</p>
        </article>
        <article class="metric-card">
          <p class="label m-0">{runtimeCopy.campaigns.liveCampaignsLabel}</p>
          <p class="m-0 font-display text-[2rem] leading-none">{overview.summary.live_campaign_count}</p>
        </article>
        <article class="metric-card">
          <p class="label m-0">{runtimeCopy.campaigns.activeSessionsLabel}</p>
          <p class="m-0 font-display text-[2rem] leading-none">{overview.summary.active_session_count}</p>
        </article>
      </div>
    </article>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <section class="band grid gap-5 px-6 py-7 md:px-8">
        <div class="grid gap-2">
          <p class="eyebrow">{runtimeCopy.campaigns.blankPathEyebrow}</p>
          <h3 class="font-display text-[1.8rem] leading-tight">{runtimeCopy.campaigns.blankPathTitle}</h3>
          <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{runtimeCopy.campaigns.blankPathDescription}</p>
        </div>
        <div class="flex flex-wrap gap-3">
          <a class="button-primary" href="/admin/campaigns/new">{runtimeCopy.campaigns.createDraftLabel}</a>
        </div>
      </section>

      <aside class="band-soft grid content-start gap-4 px-5 py-5">
        <div class="grid gap-2">
          <p class="eyebrow">{runtimeCopy.campaigns.seedPathEyebrow}</p>
          <h3 class="font-display text-[1.65rem] leading-tight">{runtimeCopy.campaigns.seedPathTitle}</h3>
          <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{runtimeCopy.campaigns.seedPathDescription}</p>
        </div>

        {#if overview.seeds.length > 0}
          <div class="grid gap-3 border-t border-[color:var(--line)] pt-4">
            {#each overview.seeds as seed}
              <article class="grid gap-2">
                <div class="grid gap-1">
                  <p class="label m-0">{seed.title}</p>
                  <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{seed.description}</p>
                  <p class="m-0 text-xs text-[color:var(--muted)]">Sample {seed.min_n} to {seed.max_n}</p>
                </div>
                <button
                  class="button-secondary w-fit"
                  type="button"
                  disabled={Boolean(seedPending)}
                  on:click={() => createFromSeed(seed.slug)}
                >
                  {seedPending === seed.slug ? 'Creating...' : runtimeCopy.campaigns.startFromSeedLabel}
                </button>
              </article>
            {/each}
          </div>
        {:else}
          <p class="m-0 text-sm text-[color:var(--muted)]">
            No bundle seeds are declared for {runtimeContext?.bundle_name ?? 'the mounted bundle'}.
          </p>
        {/if}
      </aside>
    </section>

    {#if error}
      <section class="px-1 text-sm text-ember">{error}</section>
    {/if}

    <section class="band grid gap-0 overflow-hidden">
      <header class="grid gap-2 border-b border-[color:var(--line)] px-6 py-5 md:px-8">
        <p class="eyebrow m-0">{runtimeContext?.ui.admin.current_path_label ?? 'Current path'}</p>
        <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
          {runtimeContext?.ui.admin.current_path_description ??
            'Sign in, review campaigns, launch seeded studies, move drafts live, and inspect participant transcripts from the same workspace.'}
        </p>
      </header>

      {#if overview.items.length === 0}
        <article class="px-6 py-6 text-sm text-[color:var(--muted)] md:px-8">
          No campaigns yet. Start a blank draft or launch a bundle seed.
        </article>
      {:else}
        <div class="stack-list">
          {#each overview.items as item}
            <article class="stack-row md:px-8">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div class="grid gap-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="status-badge" data-tone="neutral">{campaignSourceLabel(item.campaign.source)}</span>
                    <span class="status-badge" data-tone={campaignStateTone(item.campaign.state)}>
                      {campaignStateLabel(item.campaign.state)}
                    </span>
                    <span class="status-badge" data-tone={item.readiness.ready_for_review ? 'moss' : 'ember'}>
                      {item.readiness.completed}/{item.readiness.total} checks
                    </span>
                  </div>

                  <div class="grid gap-2">
                    <h3 class="m-0 font-display text-[1.7rem] leading-tight">{item.campaign.title}</h3>
                    <p class="m-0 max-w-3xl text-sm leading-7 text-[color:var(--muted)]">{reviewSummary(item)}</p>
                  </div>
                </div>

                <div class="grid gap-3 text-right">
                  <p class="label m-0">Updated {campaignActivityLabel(item)}</p>
                  <a class="button-primary" href={`/admin/campaigns/${item.campaign.id}`}>
                    {runtimeCopy.campaigns.openCampaignLabel}
                  </a>
                </div>
              </div>

              <div class="grid gap-4 border-t border-[color:var(--line)] pt-4 md:grid-cols-[repeat(4,minmax(0,1fr))]">
                <div class="grid gap-1">
                  <p class="label m-0">Outline</p>
                  <p class="m-0 text-sm text-[color:var(--text)]">
                    {item.readiness.ready_for_review ? 'Ready for review' : 'Collecting brief'}
                  </p>
                </div>
                <div class="grid gap-1">
                  <p class="label m-0">Invites</p>
                  <p class="m-0 text-sm text-[color:var(--text)]">
                    {item.metrics.active_invite_count} active · {item.metrics.used_invite_count} used · {item.metrics.revoked_invite_count} revoked
                  </p>
                </div>
                <div class="grid gap-1">
                  <p class="label m-0">Sessions</p>
                  <p class="m-0 text-sm text-[color:var(--text)]">
                    {item.metrics.active_session_count} active · {item.metrics.finished_session_count} finished
                  </p>
                </div>
                <div class="grid gap-1">
                  <p class="label m-0">Next states</p>
                  <p class="m-0 text-sm text-[color:var(--text)]">
                    {item.next_states.length > 0
                      ? item.next_states.map((state) => campaignStateLabel(state)).join(' -> ')
                      : 'No forward transition until the current gate is met.'}
                  </p>
                </div>
              </div>
            </article>
          {/each}
        </div>
      {/if}
    </section>
  </section>
{/if}

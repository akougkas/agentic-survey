<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, postJson } from '$lib/api';
  import { getAdminSession } from '$lib/admin';
  import { demoCopy } from '$lib/demo-copy';
  import { getBundleCatalog, getModelCatalog } from '$lib/runtime';
  import type { BundleCatalogResponse, Campaign, CatalogEntry } from '$lib/types';

  let title = 'Interview Baseline';
  let minN = 12;
  let maxN = 40;
  let pending = false;
  let seedPending = '';
  let error = '';
  let catalog: BundleCatalogResponse | null = null;
  let chatterCatalog: CatalogEntry[] = [];
  let scientistCatalog: CatalogEntry[] = [];
  let selectedChatterModel = '';
  let selectedScientistModel = '';

  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;
  $: defaultChatterCatalogId = pickDefaultCatalogId(chatterCatalog);
  $: defaultScientistCatalogId = pickDefaultCatalogId(scientistCatalog);

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      const [bundleCatalog, chatterEntries, scientistEntries] = await Promise.all([
        getBundleCatalog(),
        getModelCatalog('chatter'),
        getModelCatalog('scientist')
      ]);
      catalog = bundleCatalog;
      chatterCatalog = chatterEntries;
      scientistCatalog = scientistEntries;
      selectedChatterModel = pickDefaultCatalogId(chatterEntries);
      selectedScientistModel = pickDefaultCatalogId(scientistEntries);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to check the current session.';
    }
  });

  function pickDefaultCatalogId(entries: CatalogEntry[]): string {
    return entries.find((entry) => entry.is_default)?.catalog_id ?? entries[0]?.catalog_id ?? '';
  }

  async function createCampaign(): Promise<void> {
    error = '';
    pending = true;

    try {
      const agentModels: Record<string, string> = {};
      if (selectedChatterModel && selectedChatterModel !== defaultChatterCatalogId) {
        agentModels.chatter = selectedChatterModel;
      }
      if (selectedScientistModel && selectedScientistModel !== defaultScientistCatalogId) {
        agentModels.scientist = selectedScientistModel;
      }
      const campaign = await postJson<Campaign>('/campaigns', {
        title,
        min_n: minN,
        max_n: maxN,
        ...(Object.keys(agentModels).length > 0 ? { agent_models: agentModels } : {})
      });
      await goto(`/admin/campaigns/${campaign.id}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to create the draft right now.';
    } finally {
      pending = false;
    }
  }

  async function createFromSeed(seedSlug: string): Promise<void> {
    error = '';
    seedPending = seedSlug;

    try {
      const campaign = await postJson<Campaign>('/campaigns/from-seed', {
        seed_slug: seedSlug
      });
      await goto(`/admin/campaigns/${campaign.id}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to create the seeded campaign right now.';
    } finally {
      seedPending = '';
    }
  }
</script>

<section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
  <form class="band grid gap-6 px-6 py-7 md:px-8" on:submit|preventDefault={createCampaign}>
    <div class="grid gap-3">
      <p class="eyebrow">{demoCopy.campaigns.blankPathEyebrow}</p>
      <h2 class="section-title md:text-[2.8rem]">{demoCopy.campaigns.blankPathTitle}</h2>
      <p class="section-copy">
        {demoCopy.campaigns.blankPathDescription}
      </p>
    </div>

    <label class="grid gap-2">
      <span class="label">Campaign title</span>
      <input bind:value={title} class="field" placeholder="Interview Baseline" />
    </label>

    <div class="grid gap-4 md:grid-cols-2">
      <label class="grid gap-2">
        <span class="label">Minimum interviews</span>
        <input bind:value={minN} min="1" type="number" class="field" />
      </label>

      <label class="grid gap-2">
        <span class="label">Maximum interviews</span>
        <input bind:value={maxN} min={minN} type="number" class="field" />
      </label>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <label class="grid gap-2">
        <span class="label">Chatter model</span>
        <select bind:value={selectedChatterModel} class="field" disabled={chatterCatalog.length === 0}>
          {#each chatterCatalog as entry}
            <option value={entry.catalog_id}>{entry.label}</option>
          {/each}
        </select>
        <span class="text-xs leading-6 text-[color:var(--muted)]">
          {selectedChatterModel === defaultChatterCatalogId ? 'Role default' : 'Campaign override'}
        </span>
      </label>

      <label class="grid gap-2">
        <span class="label">Scientist model</span>
        <select bind:value={selectedScientistModel} class="field" disabled={scientistCatalog.length === 0}>
          {#each scientistCatalog as entry}
            <option value={entry.catalog_id}>{entry.label}</option>
          {/each}
        </select>
        <span class="text-xs leading-6 text-[color:var(--muted)]">
          {selectedScientistModel === defaultScientistCatalogId ? 'Role default' : 'Campaign override'}
        </span>
      </label>
    </div>

    {#if error}
      <p class="m-0 text-sm text-ember">{error}</p>
    {/if}

    <button
      class="button-primary w-fit"
      disabled={pending || !title.trim() || minN < 1 || maxN < minN}
    >
      {pending ? 'Starting draft...' : demoCopy.campaigns.createDraftLabel}
    </button>
  </form>

  <aside class="grid content-start gap-4">
    <section class="band-soft grid gap-3 px-5 py-5">
      <p class="eyebrow">{demoCopy.campaigns.readinessEyebrow}</p>
      <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
        Mira turns a manual brief into a reviewable outline, updates it after every operator turn, and keeps the review gate visible while you design.
      </p>
    </section>

    {#if catalog}
      <section class="band-soft grid gap-3 px-5 py-5">
        <p class="eyebrow">{demoCopy.campaigns.seedPathEyebrow}</p>
        <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
          Mounted product: {catalog.bundle.name}. {demoCopy.campaigns.seedPathDescription}
        </p>

        <div class="grid gap-3">
          {#each catalog.seeds as seed}
            <article class="grid gap-2 border-t border-[color:var(--line)] pt-3 first:border-t-0 first:pt-0">
              <div class="grid gap-1">
                <p class="label m-0">{seed.title}</p>
                <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{seed.description}</p>
                <p class="m-0 text-xs text-[color:var(--muted)]">
                  Sample {seed.min_n} to {seed.max_n}
                </p>
              </div>
              <button
                class="button-primary w-fit"
                type="button"
                disabled={Boolean(seedPending)}
                on:click={() => createFromSeed(seed.slug)}
              >
                {seedPending === seed.slug ? 'Creating...' : demoCopy.campaigns.startFromSeedLabel}
              </button>
            </article>
          {/each}
        </div>
      </section>
    {/if}
  </aside>
</section>

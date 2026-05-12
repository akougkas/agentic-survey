<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { createEntry, deleteEntry, listCatalog, updateEntry } from '$lib/admin-models';
  import { ApiError } from '$lib/api';
  import { getAdminSession } from '$lib/admin';
  import type {
    AgentRole,
    CatalogEntry,
    CatalogEntryPayload,
    Endpoint,
    ReasoningKwarg,
    ReasoningMode
  } from '$lib/types';

  const roleOrder: AgentRole[] = ['chatter', 'scientist', 'validator', 'analyst', 'embedding', 'ingest'];
  const endpointOptions: Endpoint[] = ['chatter', 'scientist'];
  const reasoningModeOptions: ReasoningMode[] = ['off', 'on', 'budget'];
  const reasoningKwargOptions: ReasoningKwarg[] = ['enable_thinking', 'reasoning_effort', 'none'];
  const roleLabels: Record<AgentRole, string> = {
    chatter: 'Chatter',
    scientist: 'Scientist',
    validator: 'Validator',
    analyst: 'Analyst',
    embedding: 'Embedding',
    ingest: 'Ingest'
  };

  let entries: CatalogEntry[] = [];
  let loading = true;
  let saving = false;
  let deletingKey = '';
  let error = '';
  let editorOpen = false;
  let editorMode: 'create' | 'edit' = 'create';
  let editingKey = '';
  let form = blankEntry('chatter');

  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;
  $: groupedEntries = roleOrder.map((role) => ({
    role,
    label: roleLabels[role],
    items: entries.filter((entry) => entry.role === role)
  }));

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      await loadEntries();
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to load the model catalog.';
      loading = false;
    }
  });

  function blankEntry(role: AgentRole): CatalogEntryPayload {
    return {
      catalog_id: '',
      role,
      endpoint: defaultEndpointForRole(role),
      model_id: '',
      label: '',
      notes: '',
      enabled: true,
      is_default: false,
      reasoning_mode: 'off',
      reasoning_budget_tokens: null,
      reasoning_kwarg: 'enable_thinking',
      temperature: null
    };
  }

  function defaultEndpointForRole(role: AgentRole): Endpoint {
    return role === 'chatter' ? 'chatter' : 'scientist';
  }

  function endpointLabel(endpoint: Endpoint): string {
    return endpoint === 'chatter' ? 'Chatter' : 'Scientist';
  }

  function optionalNumber(value: string): number | null {
    const trimmed = value.trim();
    if (!trimmed) {
      return null;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function optionalInteger(value: string): number | null {
    const parsed = optionalNumber(value);
    if (parsed === null) {
      return null;
    }
    return Number.isInteger(parsed) ? parsed : Math.trunc(parsed);
  }

  function formatOptionalNumber(value: number | null | undefined): string {
    return value === null || value === undefined ? '' : String(value);
  }

  function handleRoleChange(role: AgentRole): void {
    const previousDefault = defaultEndpointForRole(form.role);
    form.role = role;
    if (form.endpoint === previousDefault) {
      form.endpoint = defaultEndpointForRole(role);
    }
  }

  function normalizedForm(): CatalogEntryPayload {
    return {
      ...form,
      catalog_id: form.catalog_id.trim(),
      model_id: form.model_id.trim(),
      label: form.label.trim(),
      notes: form.notes?.trim() || null,
      reasoning_budget_tokens: form.reasoning_budget_tokens ?? null,
      temperature: form.temperature ?? null
    };
  }

  function entryKey(entry: Pick<CatalogEntry, 'catalog_id' | 'role'>): string {
    return `${entry.catalog_id}/${entry.role}`;
  }

  async function loadEntries(): Promise<void> {
    loading = true;
    error = '';
    try {
      entries = await listCatalog();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to load the model catalog.';
    } finally {
      loading = false;
    }
  }

  function startCreate(role: AgentRole): void {
    editorMode = 'create';
    editingKey = '';
    form = blankEntry(role);
    editorOpen = true;
    error = '';
  }

  function startEdit(entry: CatalogEntry): void {
    editorMode = 'edit';
    editingKey = entryKey(entry);
    form = {
      catalog_id: entry.catalog_id,
      role: entry.role,
      endpoint: entry.endpoint,
      model_id: entry.model_id,
      label: entry.label,
      notes: entry.notes ?? '',
      enabled: entry.enabled,
      is_default: entry.is_default,
      reasoning_mode: entry.reasoning_mode ?? 'off',
      reasoning_budget_tokens: entry.reasoning_budget_tokens ?? null,
      reasoning_kwarg: entry.reasoning_kwarg ?? 'none',
      temperature: entry.temperature ?? null
    };
    editorOpen = true;
    error = '';
  }

  function closeEditor(): void {
    editorOpen = false;
    editingKey = '';
    form = blankEntry('chatter');
  }

  async function submitForm(): Promise<void> {
    saving = true;
    error = '';
    try {
      const payload = normalizedForm();
      if (editorMode === 'edit') {
        await updateEntry(payload.catalog_id, payload.role, {
          endpoint: payload.endpoint,
          model_id: payload.model_id,
          label: payload.label,
          notes: payload.notes,
          enabled: payload.enabled,
          is_default: payload.is_default,
          reasoning_mode: payload.reasoning_mode,
          reasoning_budget_tokens: payload.reasoning_budget_tokens,
          reasoning_kwarg: payload.reasoning_kwarg,
          temperature: payload.temperature
        });
      } else {
        await createEntry(payload);
      }
      await loadEntries();
      closeEditor();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to save that model entry.';
    } finally {
      saving = false;
    }
  }

  async function toggleEnabled(entry: CatalogEntry): Promise<void> {
    error = '';
    try {
      await updateEntry(entry.catalog_id, entry.role, {
        enabled: !entry.enabled,
        is_default: !entry.enabled ? false : entry.is_default
      });
      await loadEntries();
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to update that entry.';
    }
  }

  async function removeEntry(entry: CatalogEntry): Promise<void> {
    if (!window.confirm(`Delete ${entry.catalog_id} for ${roleLabels[entry.role]}?`)) {
      return;
    }

    deletingKey = entryKey(entry);
    error = '';
    try {
      await deleteEntry(entry.catalog_id, entry.role);
      await loadEntries();
      if (editingKey === entryKey(entry)) {
        closeEditor();
      }
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to delete that entry.';
    } finally {
      deletingKey = '';
    }
  }
</script>

{#if loading}
  <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Loading model catalog...</article>
{:else}
  <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
    <section class="band grid gap-0 overflow-hidden">
      <header class="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--line)] px-6 py-5">
        <div class="grid gap-2">
          <p class="eyebrow m-0">Model catalog</p>
          <h2 class="section-title">Runtime model catalog</h2>
        </div>
        <button class="button-primary" type="button" on:click={() => startCreate('chatter')}>Add model</button>
      </header>

      {#each groupedEntries as group, index}
        <section class={`grid gap-0 ${index > 0 ? 'border-t border-[color:var(--line)]' : ''}`}>
          <div class="flex flex-wrap items-center justify-between gap-3 px-6 py-5">
            <div class="grid gap-1">
              <p class="label m-0">{group.label}</p>
              <p class="m-0 text-sm text-[color:var(--muted)]">{group.items.length} entries</p>
            </div>
            <button class="button-secondary" type="button" on:click={() => startCreate(group.role)}>Add</button>
          </div>

          {#if group.items.length === 0}
            <div class="px-6 pb-5 text-sm text-[color:var(--muted)]">No entries yet.</div>
          {:else}
            <div class="stack-list border-t border-[color:var(--line)]">
              {#each group.items as entry}
                <article class="stack-row">
                  <div class="grid gap-4 xl:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_minmax(0,16rem)_auto] xl:items-start">
                    <div class="grid gap-2">
                      <p class="label m-0">Catalog ID</p>
                      <p class="m-0 break-all text-sm text-[color:var(--text)]">{entry.catalog_id}</p>
                    </div>

                    <div class="grid gap-2">
                      <div class="flex flex-wrap items-center gap-2">
                        <p class="m-0 text-sm text-[color:var(--text)]">{entry.label}</p>
                        <span class="status-badge" data-tone={entry.enabled ? 'moss' : 'neutral'}>
                          {entry.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        {#if entry.is_default}
                          <span class="status-badge" data-tone="brass">Default</span>
                        {/if}
                      </div>
                      <p class="m-0 break-all text-xs leading-6 text-[color:var(--muted)]">{entry.model_id}</p>
                      {#if entry.notes}
                        <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{entry.notes}</p>
                      {/if}
                    </div>

                    <div class="grid gap-2">
                      <p class="label m-0">Endpoint</p>
                      <p class="m-0 text-sm text-[color:var(--text)]">{endpointLabel(entry.endpoint)}</p>
                      <p class="m-0 text-xs leading-6 text-[color:var(--muted)]">
                        reasoning {entry.reasoning_mode}
                        {#if entry.reasoning_budget_tokens}
                          ; {entry.reasoning_budget_tokens} tokens
                        {/if}
                        {#if entry.temperature !== null && entry.temperature !== undefined}
                          ; temp {entry.temperature}
                        {/if}
                      </p>
                    </div>

                    <div class="flex flex-wrap justify-start gap-2 xl:justify-end">
                      <button class="button-secondary" type="button" on:click={() => startEdit(entry)}>Edit</button>
                      <button class="button-secondary" type="button" on:click={() => toggleEnabled(entry)}>
                        {entry.enabled ? 'Disable' : 'Enable'}
                      </button>
                      <button
                        class="button-danger"
                        type="button"
                        disabled={deletingKey === entryKey(entry)}
                        on:click={() => removeEntry(entry)}
                      >
                        {deletingKey === entryKey(entry) ? 'Deleting...' : 'Delete'}
                      </button>
                    </div>
                  </div>
                </article>
              {/each}
            </div>
          {/if}
        </section>
      {/each}
    </section>

    <aside class="band grid content-start gap-5 px-6 py-6">
      <div class="grid gap-2">
        <p class="eyebrow">{editorMode === 'edit' ? 'Edit entry' : 'New entry'}</p>
        <h3 class="font-display text-[1.65rem] leading-tight">
          {editorOpen ? (editorMode === 'edit' ? 'Update model' : 'Add model') : 'Pick a role to start'}
        </h3>
      </div>

      {#if editorOpen}
        <form class="grid gap-4 border-t border-[color:var(--line)] pt-4" on:submit|preventDefault={submitForm}>
          <label class="grid gap-2">
            <span class="label">Catalog ID</span>
            <input bind:value={form.catalog_id} class="field" disabled={editorMode === 'edit'} />
          </label>

          <label class="grid gap-2">
            <span class="label">Role</span>
            <select
              value={form.role}
              class="field"
              disabled={editorMode === 'edit'}
              on:change={(event) => handleRoleChange((event.currentTarget as HTMLSelectElement).value as AgentRole)}
            >
              {#each roleOrder as role}
                <option value={role}>{roleLabels[role]}</option>
              {/each}
            </select>
          </label>

          <label class="grid gap-2">
            <span class="label">Endpoint</span>
            <select bind:value={form.endpoint} class="field">
              {#each endpointOptions as endpoint}
                <option value={endpoint}>{endpointLabel(endpoint)}</option>
              {/each}
            </select>
          </label>

          <label class="grid gap-2">
            <span class="label">Label</span>
            <input bind:value={form.label} class="field" />
          </label>

          <label class="grid gap-2">
            <span class="label">Model ID</span>
            <input bind:value={form.model_id} class="field" />
          </label>

          <label class="grid gap-2">
            <span class="label">Notes</span>
            <textarea bind:value={form.notes} class="field min-h-[7rem]"></textarea>
          </label>

          <div class="grid gap-4 border-y border-[color:var(--line)] py-4">
            <div class="grid gap-4 md:grid-cols-2">
              <label class="grid gap-2">
                <span class="label">Reasoning mode</span>
                <select bind:value={form.reasoning_mode} class="field">
                  {#each reasoningModeOptions as mode}
                    <option value={mode}>{mode}</option>
                  {/each}
                </select>
              </label>

              <label class="grid gap-2">
                <span class="label">Reasoning kwarg</span>
                <select bind:value={form.reasoning_kwarg} class="field">
                  {#each reasoningKwargOptions as kwarg}
                    <option value={kwarg}>{kwarg}</option>
                  {/each}
                </select>
              </label>
            </div>

            <div class="grid gap-4 md:grid-cols-2">
              <label class="grid gap-2">
                <span class="label">Reasoning budget tokens</span>
                <input
                  value={formatOptionalNumber(form.reasoning_budget_tokens)}
                  min="1"
                  step="1"
                  type="number"
                  class="field"
                  placeholder="Default"
                  on:input={(event) =>
                    (form.reasoning_budget_tokens = optionalInteger(
                      (event.currentTarget as HTMLInputElement).value
                    ))}
                />
              </label>

              <label class="grid gap-2">
                <span class="label">Temperature</span>
                <input
                  value={formatOptionalNumber(form.temperature)}
                  min="0"
                  max="2"
                  step="0.05"
                  type="number"
                  class="field"
                  placeholder="Default"
                  on:input={(event) =>
                    (form.temperature = optionalNumber((event.currentTarget as HTMLInputElement).value))}
                />
              </label>
            </div>
          </div>

          <label class="flex items-center gap-3 text-sm text-[color:var(--muted)]">
            <input bind:checked={form.enabled} type="checkbox" />
            <span>Enabled</span>
          </label>

          <label class="flex items-center gap-3 text-sm text-[color:var(--muted)]">
            <input bind:checked={form.is_default} type="checkbox" />
            <span>Default for {roleLabels[form.role]}</span>
          </label>

          <div class="flex flex-wrap gap-2">
            <button
              class="button-primary"
              disabled={
                saving || !form.catalog_id.trim() || !form.label.trim() || !form.model_id.trim()
              }
            >
              {saving ? 'Saving...' : editorMode === 'edit' ? 'Save changes' : 'Create entry'}
            </button>
            <button class="button-secondary" type="button" on:click={closeEditor}>Cancel</button>
          </div>
        </form>
      {:else}
        <div class="grid gap-3 border-t border-[color:var(--line)] pt-4">
          {#each roleOrder as role}
            <button class="button-secondary justify-start" type="button" on:click={() => startCreate(role)}>
              Add {roleLabels[role]}
            </button>
          {/each}
        </div>
      {/if}

      {#if error}
        <p class="m-0 text-sm text-ember">{error}</p>
      {/if}
    </aside>
  </section>
{/if}

<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { createEntry, deleteEntry, listCatalog, updateEntry } from '$lib/admin-models';
  import { ApiError } from '$lib/api';
  import { getAdminSession } from '$lib/admin';
  import type { AgentRole, CatalogEntry, CatalogEntryPayload } from '$lib/types';

  const roleOrder: AgentRole[] = ['chatter', 'scientist', 'validator', 'analyst', 'embedding', 'ingest'];
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
      endpoint: role === 'chatter' ? 'mini' : 'dynamo',
      model_id: '',
      label: '',
      notes: '',
      enabled: true,
      is_default: false
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
      is_default: entry.is_default
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
      if (editorMode === 'edit') {
        await updateEntry(form.catalog_id, form.role, {
          endpoint: form.endpoint,
          model_id: form.model_id,
          label: form.label,
          notes: form.notes?.trim() || null,
          enabled: form.enabled,
          is_default: form.is_default
        });
      } else {
        await createEntry({
          ...form,
          notes: form.notes?.trim() || null
        });
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
                      <p class="m-0 text-sm text-[color:var(--text)]">{entry.endpoint}</p>
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
            <select bind:value={form.role} class="field" disabled={editorMode === 'edit'}>
              {#each roleOrder as role}
                <option value={role}>{roleLabels[role]}</option>
              {/each}
            </select>
          </label>

          <label class="grid gap-2">
            <span class="label">Endpoint</span>
            <select bind:value={form.endpoint} class="field">
              <option value="mini">mini</option>
              <option value="dynamo">dynamo</option>
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

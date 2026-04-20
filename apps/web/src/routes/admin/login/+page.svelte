<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, postJson } from '$lib/api';
  import { getAdminSession } from '$lib/admin';
  import type { AdminSessionResponse } from '$lib/types';

  let password = '';
  let pending = false;
  let error = '';

  $: nextPath = $page.url.searchParams.get('next') || '/admin/campaigns';
  $: runtimeContext = $page.data.runtimeContext ?? null;

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (session?.authenticated) {
        await goto(nextPath);
      }
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to check the current session.';
    }
  });

  async function handleLogin(): Promise<void> {
    error = '';
    pending = true;

    try {
      await postJson<AdminSessionResponse>('/admin/login', { password });
      await goto(nextPath);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to sign in right now.';
    } finally {
      pending = false;
    }
  }
</script>

<section class="grid gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
  <form class="band grid gap-6 px-6 py-7 md:px-8" on:submit|preventDefault={handleLogin}>
    <div class="grid gap-3">
      <p class="eyebrow">{runtimeContext?.ui.admin.login_eyebrow ?? 'Operator Access'}</p>
      <h2 class="section-title md:text-[2.8rem]">Enter the operator password.</h2>
      <p class="section-copy">
        {runtimeContext?.ui.admin.login_description ??
          'Access stays behind the environment variable gate. The default remains `change-me` until you replace it.'}
      </p>
    </div>

    <label class="grid gap-2">
      <span class="label">Password</span>
      <input
        type="password"
        bind:value={password}
        class="field"
        placeholder="SURVEY_ADMIN_PASSWORD"
      />
    </label>

    {#if error}
      <p class="m-0 text-sm text-ember">{error}</p>
    {/if}

    <button class="button-primary w-fit" disabled={pending || !password.trim()}>
      {pending ? 'Checking...' : 'Enter workspace'}
    </button>
  </form>

  <aside class="grid content-start gap-6">
    <section class="grid gap-3">
      <p class="eyebrow">{runtimeContext?.ui.admin.boundary_eyebrow ?? 'Operator boundary'}</p>
      <p class="section-copy">
        {runtimeContext?.ui.admin.boundary_description ??
          'Admin access stays behind the runtime password gate. Product identity, seed campaigns, and deployment config come from the mounted bundle instead of the shared UI shell.'}
      </p>
    </section>

    <section class="band-soft grid gap-3 px-5 py-5">
      <p class="label m-0">{runtimeContext?.ui.admin.current_path_label ?? 'Current path'}</p>
      <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
        {runtimeContext?.ui.admin.current_path_description ??
          'Sign in, review campaigns, launch seeded studies, move drafts live, and inspect participant transcripts from the same workspace.'}
      </p>
    </section>
  </aside>
</section>

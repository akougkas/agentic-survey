<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  import { ApiError, getJson } from '$lib/api';
  import type { SessionBundleResponse } from '$lib/types';

  let loading = true;
  let error = '';

  onMount(async () => {
    try {
      const bundle = await getJson<SessionBundleResponse>('/sessions/me');
      await goto(`/chat/${bundle.session.id}`);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 404 || caught.status === 401)) {
        error = 'No active session. Redeem an invitation to begin.';
      } else if (caught instanceof ApiError) {
        error = caught.message;
      } else {
        error = 'Unable to look up your session.';
      }
    } finally {
      loading = false;
    }
  });
</script>

<section class="grid gap-6">
  {#if loading}
    <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Checking for an active session...</article>
  {:else}
    <article class="band grid gap-4 px-6 py-6">
      <p class="eyebrow">Participant path</p>
      <h2 class="font-display text-3xl">{error}</h2>
      <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
        Open the invitation link you received to start a session with Mira.
      </p>
    </article>
  {/if}
</section>

<script lang="ts">
  import { page } from '$app/stores';

  $: home = $page.data.runtimeContext?.ui.home ?? null;
</script>

<svelte:head>
  <title>Open your invitation</title>
</svelte:head>

<article class="prose-reader">
  <p class="eyebrow">{home?.participant_path_label ?? 'Participant path'}</p>
  <h1 class="reader-title">Open the invitation link from your email.</h1>
  <p class="reader-body">
    Each conversation begins with a single-use link sent by the study team.
    The link carries the invitation token and lands you in the consent
    document before Mira opens.
  </p>
  <p class="reader-body">
    If you do not have an invitation, the study team will share one when
    your slot is available.
  </p>
</article>

<script lang="ts">
  import { page } from '$app/stores';

  $: runtimeContext = $page.data.runtimeContext ?? null;
  $: home = runtimeContext?.ui.home ?? null;
  $: branding = runtimeContext?.branding ?? null;
</script>

<article class="landing">
  <section class="landing-mast">
    <p class="eyebrow">{home?.eyebrow ?? 'Agentic Survey'}</p>
    <h1 class="landing-headline">
      {branding?.title ?? 'Structured interview campaigns with Mira.'}
    </h1>
    <p class="landing-lede">
      {branding?.description ??
        'Design a campaign, invite participants, and review transcript signal from a reusable runtime that can mount product bundles cleanly.'}
    </p>
  </section>

  <section class="landing-paths" aria-label="Choose a path">
    <a class="landing-path" href="/invite">
      <p class="label landing-path-label">{home?.participant_path_label ?? 'Participant path'}</p>
      <h2 class="landing-path-title">If you have an invite, begin here.</h2>
      <span class="landing-path-cue">Open the invitation
        <span aria-hidden="true" class="landing-path-arrow">→</span></span>
    </a>

    <a class="landing-path" href="/admin/campaigns">
      <p class="label landing-path-label">{home?.operator_path_label ?? 'Operator path'}</p>
      <h2 class="landing-path-title">Open the admin console.</h2>
      <span class="landing-path-cue">Sign in
        <span aria-hidden="true" class="landing-path-arrow">→</span></span>
    </a>
  </section>

  <aside class="landing-aside">
    <p class="eyebrow">About {home?.persona_panel_title ?? 'Mira'}</p>
    <p class="landing-aside-body">
      {home?.persona_panel_description ??
        'A synthetic field researcher with a measured voice, sharp memory, and no appetite for vague answers.'}
    </p>
  </aside>
</article>

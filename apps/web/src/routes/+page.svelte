<script lang="ts">
  import { page } from '$app/stores';

  $: runtimeContext = $page.data.runtimeContext ?? null;
  $: home = runtimeContext?.ui.home ?? null;
  $: branding = runtimeContext?.branding ?? null;
  $: personaQuote = firstSentence(home?.persona_panel_description ?? '');
  $: personaTrailing = trailingSentences(home?.persona_panel_description ?? '');

  function firstSentence(text: string): string {
    if (!text) return '';
    const collapsed = text.replace(/\s+/g, ' ').trim();
    const match = collapsed.match(/[^.?!]*[.?!]/);
    return match ? match[0].trim() : collapsed;
  }

  function trailingSentences(text: string): string {
    if (!text) return '';
    const collapsed = text.replace(/\s+/g, ' ').trim();
    const lead = firstSentence(collapsed);
    if (!lead || lead === collapsed) return '';
    return collapsed.slice(lead.length).trim();
  }
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
      <span class="landing-path-cue">
        Open the invitation
        <svg
          class="landing-path-arrow"
          width="16"
          height="10"
          viewBox="0 0 16 10"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M0 5h13.5M9.5 1l4 4-4 4"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
    </a>

    <a class="landing-path" href="/admin/campaigns">
      <p class="label landing-path-label">{home?.operator_path_label ?? 'Operator path'}</p>
      <h2 class="landing-path-title">Open the admin console.</h2>
      <span class="landing-path-cue">
        Sign in
        <svg
          class="landing-path-arrow"
          width="16"
          height="10"
          viewBox="0 0 16 10"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M0 5h13.5M9.5 1l4 4-4 4"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
    </a>
  </section>

  <aside class="landing-aside">
    <p class="eyebrow">About {home?.persona_panel_title ?? 'Mira'}</p>
    {#if personaQuote}
      <p class="landing-aside-quote">{personaQuote}</p>
    {/if}
    {#if personaTrailing}
      <p class="landing-aside-body">{personaTrailing}</p>
    {:else if !personaQuote}
      <p class="landing-aside-body">
        A synthetic field researcher with a measured voice, sharp memory, and no
        appetite for vague answers.
      </p>
    {/if}
  </aside>
</article>

<script lang="ts">
  import { page } from '$app/stores';

  $: runtimeContext = $page.data.runtimeContext ?? null;
</script>

<section class="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_20rem]">
  <article class="band grid gap-8 px-6 py-7 md:px-8 md:py-8">
    <div class="grid gap-4">
      <p class="eyebrow">{runtimeContext?.ui.home.eyebrow ?? 'Operator Console'}</p>
      <h2 class="section-title md:text-[3.1rem]">
        {runtimeContext?.branding.title ?? 'Start a campaign, invite people, and review the signal.'}
      </h2>
      <p class="section-copy">
        {runtimeContext?.branding.description ??
          'The runtime can mount product bundles, seed campaigns, and keep the same operator and participant flows.'}
      </p>
    </div>

    <div class="stack-list border-t border-[color:var(--line)]">
      <a class="stack-row transition hover:bg-white/5" href="/admin/login?next=%2Fadmin%2Fcampaigns%2Fnew">
        <div class="grid gap-2">
          <p class="label m-0">{runtimeContext?.ui.home.operator_path_label ?? 'Operator path'}</p>
          <h3 class="font-display text-[1.7rem] leading-tight">
            {runtimeContext?.ui.home.operator_path_title ?? 'Design a campaign'}
          </h3>
          <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
            {runtimeContext?.ui.home.operator_path_description ??
              'Begin with Mira, define objectives, and shape the first outline.'}
          </p>
        </div>
        <span class="text-sm text-moss">Open workspace</span>
      </a>

      <a class="stack-row transition hover:bg-white/5" href="/chat">
        <div class="grid gap-2">
          <p class="label m-0">{runtimeContext?.ui.home.participant_path_label ?? 'Participant path'}</p>
          <h3 class="font-display text-[1.7rem] leading-tight">
            {runtimeContext?.ui.home.participant_path_title ?? 'Resume a session'}
          </h3>
          <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
            {runtimeContext?.ui.home.participant_path_description ??
              'Participants redeem an invitation, choose consent, and enter the interview loop.'}
          </p>
        </div>
        <span class="text-sm text-moss">Open session</span>
      </a>
    </div>
  </article>

  <aside class="grid content-start gap-4">
    <section class="band-soft grid gap-4 px-5 py-5">
      <p class="eyebrow">{runtimeContext?.ui.home.bundle_panel_title ?? 'Mounted bundle'}</p>
      <ul class="m-0 grid gap-3 pl-4 text-sm leading-7 text-[color:var(--text)]">
        <li>Active product: {runtimeContext?.bundle_name ?? 'Agentic Survey Demo'}.</li>
        <li>Bundle slug: `{runtimeContext?.bundle_slug ?? 'demo'}`.</li>
        <li>Declared seed campaigns: {runtimeContext?.campaign_seed_count ?? 0}.</li>
        <li>Swap products with `SURVEY_PRODUCT_BUNDLE_DIR`.</li>
      </ul>
    </section>

    <section class="band-soft grid gap-3 px-5 py-5">
      <p class="eyebrow">{runtimeContext?.ui.home.persona_panel_title ?? 'Mira'}</p>
      <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
        {runtimeContext?.ui.home.persona_panel_description ??
          'A synthetic field researcher with a measured voice, sharp memory, and no appetite for vague answers.'}
      </p>
    </section>
  </aside>
</section>

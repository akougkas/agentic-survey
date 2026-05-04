<script lang="ts">
  import { page } from '$app/stores';

  $: runtimeContext = $page.data.runtimeContext ?? null;
  $: productName = runtimeContext?.bundle_name ?? runtimeContext?.app_name ?? 'this study';
</script>

<svelte:head>
  <title>About — Agentic Survey</title>
</svelte:head>

<article class="prose-reader">
  <p class="eyebrow">About the platform</p>
  <h1 class="reader-title">Agentic Survey</h1>
  <p class="reader-body">
    Agentic Survey is a research-grade runtime for adaptive interview campaigns conducted by
    a single field researcher named Mira. The platform is generic; the present study,
    {productName}, is one product mounted on top of it.
  </p>
  <p class="reader-body">
    Mira holds one methodological spine across every conversation while modulating voice,
    depth, and follow-up to fit each respondent. Outline-tracking, retrieval, and concept
    extraction run continuously behind the conversation; the participant sees only the
    questions and the chips.
  </p>
  <p class="reader-body">
    Source and roadmap available on request from the study team.
  </p>
</article>

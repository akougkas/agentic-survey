<script lang="ts">
  import { page } from '$app/stores';
  import '../app.css';
  import type { LayoutData } from './$types';

  export let data: LayoutData;

  $: runtimeContext = data?.runtimeContext ?? null;
  $: pathname = $page.url.pathname;
  $: isAdminRoute = pathname.startsWith('/admin');
  $: wordmark = runtimeContext?.branding.eyebrow ?? runtimeContext?.runtime_name ?? 'Agentic Survey';
  $: pageTitle = runtimeContext?.app_name ?? 'Agentic Survey';
</script>

<svelte:head>
  <title>{pageTitle}</title>
  <link rel="icon" href="/favicon.svg" />
</svelte:head>

<a class="skip-link" href="#main">Skip to content</a>

{#if isAdminRoute}
  <div class="shell shell--admin grid gap-6">
    <main id="main" class="contents">
      <slot />
    </main>
  </div>
{:else}
  <div class="shell shell--participant grid gap-8">
    <header class="participant-mast">
      <a class="participant-wordmark" href="/" aria-label="Home">{wordmark}</a>
      <a class="participant-attribution" href="/about">
        <span class="hidden sm:inline">Powered by </span>Agentic Survey
      </a>
    </header>

    <main id="main" class="contents">
      <slot />
    </main>
  </div>
{/if}

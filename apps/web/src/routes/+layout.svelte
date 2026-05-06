<script lang="ts">
  import { page } from '$app/stores';
  import '../app.css';
  import { runtimeCopy } from '$lib/runtime-copy';
  import type { LayoutData } from './$types';

  export let data: LayoutData;

  $: runtimeContext = data?.runtimeContext ?? null;
  $: pathname = $page.url.pathname;
  $: isAdminRoute = pathname.startsWith('/admin');
  $: wordmark = runtimeContext?.branding.eyebrow ?? runtimeContext?.runtime_name ?? 'Agentic Survey';
  $: pageTitle = runtimeContext?.app_name ?? 'Agentic Survey';
  $: footer = {
    hosted_by: runtimeContext?.ui.footer?.hosted_by ?? runtimeCopy.footer.hosted_by,
    developed_by: runtimeContext?.ui.footer?.developed_by ?? runtimeCopy.footer.developed_by,
    copyright: runtimeContext?.ui.footer?.copyright ?? runtimeCopy.footer.copyright
  };
  $: hasFooterContent = Boolean(footer.hosted_by || footer.developed_by || footer.copyright);
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
      <a class="participant-attribution" href="/about"
        ><span>Powered by&nbsp;</span>Agentic Survey</a>
    </header>

    <main id="main" class="contents">
      <slot />
    </main>

    {#if hasFooterContent}
      <footer class="participant-footer" aria-label="Study credits">
        <p class="participant-footer-credits">
          {#if footer.hosted_by}
            <span>{footer.hosted_by}</span>
          {/if}
          {#if footer.developed_by}
            <span>{footer.developed_by}</span>
          {/if}
        </p>
        {#if footer.copyright}
          <p class="participant-footer-copyright">{footer.copyright}</p>
        {/if}
      </footer>
    {/if}
  </div>
{/if}

<script lang="ts">
  import '../app.css';
  import type { LayoutData } from './$types';

  export let data: LayoutData;

  const links = [
    { href: '/', label: 'Portal' },
    { href: '/admin/login?next=%2Fadmin%2Fcampaigns', label: data?.runtimeContext?.ui.admin.nav_label ?? 'Workspace' },
    { href: '/chat', label: 'Interview' }
  ];

  $: runtimeContext = data?.runtimeContext ?? null;
</script>

<svelte:head>
  <title>{runtimeContext?.app_name ?? 'Agentic Survey'}</title>
  <link rel="icon" href="/favicon.svg" />
</svelte:head>

<div class="shell grid gap-6">
  <header class="grid gap-5 border-b border-[color:var(--line)] pb-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
    <div class="grid gap-2">
      <p class="eyebrow">{runtimeContext?.branding.eyebrow ?? 'Agentic Survey'}</p>
      <h1 class="page-title max-w-3xl">{runtimeContext?.app_name ?? 'Agentic Survey'}</h1>
    </div>

    <nav class="flex flex-wrap gap-1 md:justify-end">
      {#each links as link}
        <a class="nav-link" href={link.href}>{link.label}</a>
      {/each}
    </nav>
  </header>

  <slot />
</div>

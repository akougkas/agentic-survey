<script lang="ts">
  import { page } from '$app/stores';
  import { adminLinks } from '$lib/admin';

  $: runtimeContext = $page.data.runtimeContext ?? null;
</script>

<section class="grid gap-6">
  <header class="grid gap-5 border-b border-[color:var(--line)] pb-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
    <div class="grid gap-2">
      <p class="eyebrow">{runtimeContext?.ui.admin.workspace_eyebrow ?? 'Operator Workspace'}</p>
      <h2 class="section-title">{runtimeContext?.ui.admin.workspace_title ?? 'Campaign workflow'}</h2>
    </div>

    <nav class="flex flex-wrap gap-1 md:justify-end">
      {#each adminLinks as link}
        <a class="nav-link" href={link.href}>{link.label}</a>
      {/each}
    </nav>
  </header>

  <slot />
</section>

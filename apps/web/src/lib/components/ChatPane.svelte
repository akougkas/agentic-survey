<script lang="ts">
  import { afterUpdate, createEventDispatcher } from 'svelte';
  import type { GetUserInputOptions } from '$lib/types';

  export let title: string;
  export let messages: Array<{ role: string; content: string }>;
  export let agentName = 'Mira';
  export let participantName = 'Participant';
  export let placeholder = 'Answer in your own words.';
  export let submitLabel = 'Continue';
  export let disabled = false;
  export let pending = false;
  export let emptyState = 'The conversation has not started yet.';
  export let footerNote = '';
  export let activePrompt: GetUserInputOptions | null = null;
  export let paused = false;
  export let resumePending = false;

  const dispatch = createEventDispatcher<{
    submit: { content: string };
    resume: undefined;
  }>();

  let draft = '';
  let transcriptEl: HTMLDivElement | null = null;
  let seenMessageCount = 0;
  let seenPending = false;

  function isAgent(role: string): boolean {
    return role === 'agent' || role === 'designer';
  }

  function stripTrailingChipEcho(content: string, options: string[]): string {
    if (!content) return content;
    const labels = (options ?? []).map((o) => o.trim()).filter((o) => o.length > 0);
    if (labels.length === 0) return content;
    const labelSet = new Set(labels);
    const lines = content.split('\n');
    let cutIndex = lines.length;
    let matchedCount = 0;
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const trimmed = lines[i].trim();
      if (trimmed === '') {
        if (matchedCount === 0) continue;
        if (matchedCount === labels.length) {
          cutIndex = i;
          break;
        }
        return content;
      }
      if (!labelSet.has(trimmed)) {
        if (matchedCount === labels.length) {
          cutIndex = i + 1;
          break;
        }
        return content;
      }
      matchedCount += 1;
      cutIndex = i;
    }
    if (matchedCount !== labels.length) return content;
    let end = cutIndex;
    while (end > 0 && lines[end - 1].trim() === '') end -= 1;
    return lines.slice(0, end).join('\n');
  }

  function renderAgentContent(content: string): string {
    if (!activePrompt) return content;
    return stripTrailingChipEcho(content, activePrompt.options ?? []);
  }

  function handleSubmit(): void {
    const content = draft.trim();
    if (!content || disabled || pending || paused) {
      return;
    }

    dispatch('submit', { content });
    draft = '';
  }

  function submitChip(content: string): void {
    if (disabled || pending || paused) {
      return;
    }
    dispatch('submit', { content });
  }

  function handleResume(): void {
    if (resumePending) {
      return;
    }
    dispatch('resume');
  }

  afterUpdate(() => {
    if (!transcriptEl) return;
    if (messages.length === seenMessageCount && pending === seenPending) return;
    seenMessageCount = messages.length;
    seenPending = pending;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  });
</script>

<section class="band flex min-h-[36rem] flex-col overflow-hidden">
  <header class="flex items-start justify-between gap-4 border-b border-[color:var(--line)] px-5 py-5 md:px-6">
    <div class="grid gap-1">
      <p class="eyebrow">{title}</p>
      <h2 class="section-title text-[1.8rem] md:text-[2rem]">Conversation</h2>
    </div>
    <div class="flex items-center gap-2 text-right">
      {#if pending}
        <span class="dot-pulse"><span></span><span></span><span></span></span>
        <span class="label m-0">{agentName} is thinking</span>
      {:else if disabled}
        <span class="label m-0">Transcript locked</span>
      {:else}
        <span class="label m-0">{messages.length} turns</span>
      {/if}
    </div>
  </header>

  <div bind:this={transcriptEl} class="flex-1 overflow-y-auto px-5 py-6 md:px-6">
    <div class="grid gap-4">
      {#if messages.length === 0}
        <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{emptyState}</p>
      {:else}
        {#each messages as message}
          <article
            class={`max-w-[44rem] rounded-[8px] px-5 py-4 ${
              isAgent(message.role)
                ? 'border-l-2 border-[color:rgba(126,184,141,0.46)] bg-[color:rgba(126,184,141,0.08)]'
                : 'ml-auto border-l-2 border-[color:rgba(220,125,78,0.45)] bg-[color:rgba(232,224,207,0.04)]'
            }`}
          >
            <p class="font-mono text-[11px] uppercase tracking-[0.16em] text-[color:var(--muted)] mb-2">
              {isAgent(message.role) ? agentName : participantName}
            </p>
            <p class="m-0 whitespace-pre-wrap text-[15px] leading-[1.75] text-[color:var(--text)]">
              {isAgent(message.role) ? renderAgentContent(message.content) : message.content}
            </p>
          </article>
        {/each}
        {#if pending}
          <article
            class="max-w-[44rem] rounded-[8px] border-l-2 border-[color:rgba(126,184,141,0.46)] bg-[color:rgba(126,184,141,0.08)] px-5 py-4"
          >
            <p class="font-mono text-[11px] uppercase tracking-[0.16em] text-[color:var(--muted)] mb-2">
              {agentName}
            </p>
            <div class="flex items-center gap-2">
              <span class="dot-pulse"><span></span><span></span><span></span></span>
              <span class="text-[15px] italic leading-[1.75] text-[color:var(--muted)]">is thinking…</span>
            </div>
          </article>
        {/if}
      {/if}
    </div>
  </div>

  <footer class="grid gap-4 border-t border-[color:var(--line)] px-5 py-4 md:px-6">
    {#if footerNote}
      <p class="m-0 text-sm text-[color:var(--muted)]">{footerNote}</p>
    {/if}

    {#if activePrompt && activePrompt.options.length}
      <div class="chip-list">
        {#each activePrompt.options as option}
          <button
            type="button"
            class={`chip ${option === 'Discuss this more.' ? 'chip--discuss' : ''}`}
            disabled={disabled || pending || paused}
            on:click={() => submitChip(option)}
          >
            {option}
          </button>
        {/each}
      </div>
    {/if}

    <form class="grid gap-3 md:grid-cols-[1fr_auto]" on:submit|preventDefault={handleSubmit}>
      <textarea
        rows="4"
        bind:value={draft}
        disabled={disabled || pending || paused}
        class="field min-h-[5rem] resize-none"
        placeholder={activePrompt && activePrompt.options.length
          ? 'Tap a quick anchor above, or type your own answer'
          : placeholder}
      ></textarea>
      <button
        class="button-primary md:self-end"
        disabled={disabled || pending || paused || !draft.trim()}
      >
        {pending ? 'Working...' : submitLabel}
      </button>
    </form>

    {#if paused}
      <div class="flex items-center justify-between gap-3">
        <p class="m-0 text-sm text-[color:var(--muted)]">This session is paused.</p>
        <button
          type="button"
          class="button-secondary"
          disabled={resumePending}
          on:click={handleResume}
        >
          {resumePending ? 'Resuming...' : 'Resume'}
        </button>
      </div>
    {/if}
  </footer>
</section>

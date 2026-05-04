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
    end: undefined;
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

  function isDiscussChip(option: string): boolean {
    return option.trim() === 'Discuss this more.';
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

  function handleEnd(): void {
    if (disabled || pending) {
      return;
    }
    dispatch('end');
  }

  $: anchorChips = (activePrompt?.options ?? []).filter((o) => !isDiscussChip(o));
  $: discussChip = (activePrompt?.options ?? []).find((o) => isDiscussChip(o)) ?? null;
  $: visibleMessages = messages.filter((m) => (m?.content ?? '').trim().length > 0);

  afterUpdate(() => {
    if (!transcriptEl) return;
    if (visibleMessages.length === seenMessageCount && pending === seenPending) return;
    seenMessageCount = visibleMessages.length;
    seenPending = pending;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  });
</script>

<section class="transcript">
  <header class="transcript-head">
    <div class="transcript-head-left">
      <p class="eyebrow">{title}</p>
      <p class="transcript-counter">
        {#if pending}
          <span class="dot-pulse"><span></span><span></span><span></span></span>
          <span>{agentName} is thinking</span>
        {:else if disabled}
          <span>Transcript locked</span>
        {:else}
          <span>{visibleMessages.length} turns</span>
        {/if}
      </p>
    </div>
    <button
      type="button"
      class="transcript-end"
      disabled={disabled || pending}
      on:click={handleEnd}
    >
      End conversation
    </button>
  </header>

  <div bind:this={transcriptEl} class="transcript-body">
    {#if visibleMessages.length === 0}
      <p class="transcript-empty">{emptyState}</p>
    {:else}
      {#each visibleMessages as message (message)}
        {@const agent = isAgent(message.role)}
        <article class="turn" class:turn--agent={agent} class:turn--participant={!agent}>
          <p class="turn-role">{agent ? agentName : participantName}</p>
          <p class="turn-body">
            {agent ? renderAgentContent(message.content) : message.content}
          </p>
        </article>
      {/each}
      {#if pending}
        <article class="turn turn--agent turn--pending">
          <p class="turn-role">{agentName}</p>
          <p class="turn-body turn-body--muted">
            <span class="dot-pulse"><span></span><span></span><span></span></span>
            <span>is thinking…</span>
          </p>
        </article>
      {/if}
    {/if}
  </div>

  <footer class="transcript-foot">
    {#if footerNote}
      <p class="transcript-footnote">{footerNote}</p>
    {/if}

    {#if activePrompt && (anchorChips.length || discussChip)}
      <div class="chip-row">
        {#each anchorChips as option}
          <button
            type="button"
            class="chip"
            disabled={disabled || pending || paused}
            on:click={() => submitChip(option)}
          >
            {option}
          </button>
        {/each}
        {#if discussChip}
          <button
            type="button"
            class="chip-discuss"
            disabled={disabled || pending || paused}
            on:click={() => submitChip(discussChip)}
          >
            {discussChip}
          </button>
        {/if}
      </div>
    {/if}

    <form class="transcript-compose" on:submit|preventDefault={handleSubmit}>
      <textarea
        rows="3"
        bind:value={draft}
        disabled={disabled || pending || paused}
        class="field min-h-[5rem] resize-none"
        placeholder={activePrompt && activePrompt.options.length
          ? 'Tap an anchor above, or type your own answer'
          : placeholder}
      ></textarea>
      <button
        class="button-primary transcript-submit"
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

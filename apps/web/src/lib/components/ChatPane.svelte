<script lang="ts">
  import { afterUpdate, createEventDispatcher } from 'svelte';
  import type { GetUserInputPayload, ParticipantControl } from '$lib/types';

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
  export let activePrompt: GetUserInputPayload | null = null;
  export let paused = false;
  export let resumePending = false;

  const dispatch = createEventDispatcher<{
    submit: { content: string };
    resume: undefined;
  }>();

  let draft = '';
  let transcriptEl: HTMLDivElement | null = null;
  let seenMessageCount = 0;
  const controlLabels: Record<ParticipantControl, string> = {
    continue: 'Keep going',
    skip: "I'd rather skip this",
    pause: 'Pause for now',
    stop: 'Stop here'
  };

  function isAgent(role: string): boolean {
    return role === 'agent' || role === 'designer';
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
    if (!transcriptEl || messages.length === seenMessageCount) {
      return;
    }

    seenMessageCount = messages.length;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  });
</script>

<section class="band flex min-h-[36rem] flex-col overflow-hidden">
  <header class="flex items-start justify-between gap-4 border-b border-[color:var(--line)] px-5 py-5 md:px-6">
    <div class="grid gap-1">
      <p class="eyebrow">{title}</p>
      <h2 class="section-title text-[1.8rem] md:text-[2rem]">Conversation</h2>
    </div>
    <p class="label text-right">
      {#if pending}
        {agentName} is responding
      {:else if disabled}
        Transcript locked
      {:else}
        {messages.length} turns
      {/if}
    </p>
  </header>

  <div bind:this={transcriptEl} class="flex-1 overflow-y-auto px-5 py-6 md:px-6">
    <div class="grid gap-4">
      {#if messages.length === 0}
        <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{emptyState}</p>
      {:else}
        {#each messages as message}
          <article
            class={`max-w-[44rem] rounded-[8px] px-4 py-4 ${
              isAgent(message.role)
                ? 'border-l-2 border-[color:rgba(126,184,141,0.46)] bg-[color:rgba(126,184,141,0.08)]'
                : 'ml-auto border-l-2 border-[color:rgba(220,125,78,0.45)] bg-[color:rgba(232,224,207,0.04)]'
            }`}
          >
            <p class="label mb-2">{isAgent(message.role) ? agentName : participantName}</p>
            <p class="m-0 text-sm leading-7 text-[color:var(--text)]">{message.content}</p>
          </article>
        {/each}
      {/if}
    </div>
  </div>

  <footer class="grid gap-3 border-t border-[color:var(--line)] px-5 py-4 md:px-6">
      {#if footerNote}
      <p class="m-0 text-sm text-[color:var(--muted)]">{footerNote}</p>
    {/if}

    {#if activePrompt && (activePrompt.options.length || activePrompt.participant_controls.length)}
      <div class="grid gap-3">
        {#if activePrompt.sensitive_turn}
          <p class="m-0 text-sm text-[color:var(--muted)]">
            If this part feels too personal or not worth pushing on, you can change course here.
          </p>
        {/if}

        <div class="chip-list">
          {#each activePrompt.options as option}
            <button
              type="button"
              class="chip"
              disabled={disabled || pending || paused}
              on:click={() => submitChip(option)}
            >
              {option}
            </button>
          {/each}

          {#each activePrompt.participant_controls as control}
            <button
              type="button"
              class="chip"
              disabled={disabled || pending || paused}
              on:click={() => submitChip(controlLabels[control])}
            >
              {controlLabels[control]}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <form class="grid gap-3 md:grid-cols-[1fr_auto]" on:submit|preventDefault={handleSubmit}>
      <textarea
        rows="4"
        bind:value={draft}
        disabled={disabled || pending || paused}
        class="field min-h-[7.5rem] resize-none"
        placeholder={placeholder}
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

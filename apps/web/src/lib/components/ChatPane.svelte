<script lang="ts">
  import { afterUpdate, createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
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
  export let connected = true;
  export let thinkingMessages: string[] = ['Thinking...'];
  export let streamingAgentText = '';

  const PENDING_ROTATION_MS = 2500;

  let pendingStatus = '';
  let pendingIndex = 0;
  let pendingTimer: ReturnType<typeof setInterval> | null = null;
  let lastPendingForRotation = false;

  function clearPendingTimer(): void {
    if (pendingTimer !== null) {
      clearInterval(pendingTimer);
      pendingTimer = null;
    }
  }

  function prefersReducedMotion(): boolean {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function startPendingRotation(): void {
    clearPendingTimer();
    const bank = thinkingMessages.length > 0 ? thinkingMessages : ['Thinking...'];
    pendingIndex = 0;
    pendingStatus = bank[0];
    if (prefersReducedMotion()) return;
    pendingTimer = setInterval(() => {
      const live = thinkingMessages.length > 0 ? thinkingMessages : ['Thinking...'];
      pendingIndex = (pendingIndex + 1) % live.length;
      pendingStatus = live[pendingIndex];
    }, PENDING_ROTATION_MS);
  }

  function stopPendingRotation(): void {
    clearPendingTimer();
    pendingStatus = '';
    pendingIndex = 0;
  }

  $: {
    if (pending && !lastPendingForRotation) {
      startPendingRotation();
    } else if (!pending && lastPendingForRotation) {
      stopPendingRotation();
    }
    lastPendingForRotation = pending;
  }

  onDestroy(() => {
    clearPendingTimer();
  });

  const dispatch = createEventDispatcher<{
    submit: { content: string };
    resume: undefined;
    end: undefined;
  }>();

  let draft = '';
  let transcriptEl: HTMLDivElement | null = null;
  let textareaEl: HTMLTextAreaElement | null = null;
  let pressedChip: string | null = null;
  let seenMessageCount = 0;
  let seenPending = false;
  let liveAnnouncement = '';

  $: shortTitle = computeShortTitle(title);

  function computeShortTitle(raw: string): string {
    if (!raw) return '';
    const dashIndex = raw.search(/[–—]/);
    if (dashIndex > 0) {
      return raw.slice(0, dashIndex).trim();
    }
    return raw;
  }

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

  function normalizeText(raw: string): string {
    return raw
      .toLowerCase()
      .replace(/\r?\n/g, ' ')
      .replace(/[’'`"“”]/g, '')
      .replace(/[—–-]/g, '')
      .replace(/[^\w\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function stripQuestionEcho(content: string, question: string): string {
    if (!content || !question) return content;
    const lines = content.split('\n');
    const target = normalizeText(question);
    if (!target) return content;

    let first = 0;
    while (first < lines.length && lines[first].trim() === '') {
      first += 1;
    }
    let last = lines.length - 1;
    while (last >= first && lines[last].trim() === '') {
      last -= 1;
    }
    if (first > last) return '';

    while (first <= last && normalizeText(lines[first]) === target) {
      first += 1;
    }
    while (last >= first && normalizeText(lines[last]) === target) {
      last -= 1;
    }

    const stripped = lines.slice(first, last + 1).join('\n').trim();
    return stripped || content.trim();
  }

  function renderAgentContent(content: string): string {
    if (!activePrompt) return content;
    const withQuestionStripped = stripQuestionEcho(content, activePrompt.question);
    return stripTrailingChipEcho(withQuestionStripped, activePrompt.options ?? []);
  }

  function isDiscussChip(option: string): boolean {
    return option.trim() === 'Discuss this more.';
  }

  function autoResize(): void {
    if (!textareaEl) return;
    textareaEl.style.height = 'auto';
    const next = Math.min(textareaEl.scrollHeight, Math.round(window.innerHeight * 0.5));
    textareaEl.style.height = `${next}px`;
  }

  function handleInput(): void {
    autoResize();
  }

  function handleKeydown(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      handleSubmit();
    }
  }

  function handleSubmit(): void {
    const content = draft.trim();
    if (!content || disabled || pending || paused) {
      return;
    }

    dispatch('submit', { content });
    draft = '';
    if (textareaEl) {
      textareaEl.style.height = 'auto';
    }
  }

  async function submitChip(content: string): Promise<void> {
    if (disabled || pending || paused) {
      return;
    }
    pressedChip = content;
    await tick();
    setTimeout(() => {
      pressedChip = null;
    }, 220);
    dispatch('submit', { content });
  }

  async function prefillChip(content: string): Promise<void> {
    if (disabled || pending || paused) {
      return;
    }
    pressedChip = content;
    setTimeout(() => {
      pressedChip = null;
    }, 220);

    const trimmed = content.trim();
    const existing = draft;
    const needsLeadingSpace = existing.length > 0 && !/\s$/.test(existing);
    draft = `${existing}${needsLeadingSpace ? ' ' : ''}${trimmed} `;
    liveAnnouncement = `Inserted: ${trimmed} Continue typing.`;

    await tick();
    if (textareaEl) {
      textareaEl.focus();
      const end = draft.length;
      try {
        textareaEl.setSelectionRange(end, end);
      } catch {
        // setSelectionRange throws on hidden inputs in some browsers; ignore.
      }
      autoResize();
    }
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

  function firstSentence(text: string): string {
    if (!text) return '';
    const trimmed = text.replace(/\s+/g, ' ').trim();
    const match = trimmed.match(/[^.?!]*[.?!]/);
    if (match) return match[0].trim();
    return trimmed.length > 160 ? `${trimmed.slice(0, 157).trimEnd()}…` : trimmed;
  }

  $: anchorChips = (activePrompt?.options ?? []).filter((o) => !isDiscussChip(o));
  $: discussChip = (activePrompt?.options ?? []).find((o) => isDiscussChip(o)) ?? null;
  $: visibleMessages = messages.filter((m) => (m?.content ?? '').trim().length > 0);
  $: composerInstructionId = footerNote ? 'transcript-instructions' : '';

  $: if (visibleMessages.length !== seenMessageCount) {
    const last = visibleMessages[visibleMessages.length - 1];
    if (last && isAgent(last.role)) {
      const role = `${agentName}.`;
      const lead = firstSentence(renderAgentContent(last.content));
      liveAnnouncement = `${role} ${lead}`;
    }
  }

  onMount(() => {
    autoResize();
  });

  afterUpdate(() => {
    if (!transcriptEl) return;
    if (visibleMessages.length === seenMessageCount && pending === seenPending) return;
    seenMessageCount = visibleMessages.length;
    seenPending = pending;
    if (typeof window === 'undefined') {
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
      return;
    }
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    } else {
      transcriptEl.scrollTo({ top: transcriptEl.scrollHeight, behavior: 'smooth' });
    }
  });
</script>

<section class="transcript">
  <header class="transcript-head">
    <div class="transcript-head-left">
      <p class="eyebrow transcript-eyebrow">
        <span class="hidden sm:inline">{title}</span>
        <span class="sm:hidden">{shortTitle}</span>
      </p>
      <p class="transcript-counter">
        {#if pending}
          <span class="dot-pulse" aria-hidden="true"><span></span><span></span><span></span></span>
          <span class="transcript-counter-status">{pendingStatus}</span>
        {:else if disabled}
          <span>Mira has this section saved</span>
        {:else}
          <span>Mira is listening</span>
        {/if}
      </p>
      {#if !connected && !disabled}
        <p class="transcript-disconnect" role="status">
          <span class="transcript-disconnect-dot" aria-hidden="true"></span>
          <span>Connection lost · retrying</span>
        </p>
      {/if}
    </div>
    <button
      type="button"
      class="transcript-end"
      disabled={disabled || pending}
      on:click={handleEnd}
    >
      End interview
    </button>
  </header>

  <div
    bind:this={transcriptEl}
    class="transcript-body"
    aria-live="polite"
    aria-relevant="additions"
  >
    {#if visibleMessages.length === 0}
      <p class="transcript-empty">{emptyState}</p>
    {:else}
      {#each visibleMessages as message (message)}
        {@const agent = isAgent(message.role)}
        {@const renderedContent = agent ? renderAgentContent(message.content) : message.content}
        {#if !agent || renderedContent.trim()}
          <article class="turn" class:turn--agent={agent} class:turn--participant={!agent}>
            <p class="turn-role">{agent ? agentName : participantName}</p>
            <p class="turn-body">
              {renderedContent}
            </p>
          </article>
        {/if}
      {/each}
      {#if pending}
        <article class="turn turn--agent turn--pending" aria-hidden="true">
          <p class="turn-role">{agentName}</p>
          <p
            class="turn-body"
            class:turn-body--muted={!streamingAgentText.trim()}
          >
            {#if streamingAgentText.trim()}
              {streamingAgentText}
            {:else}
              <span class="dot-pulse"><span></span><span></span><span></span></span>
              <span class="turn-pending-status">{pendingStatus}</span>
            {/if}
          </p>
        </article>
      {/if}
    {/if}
  </div>

  <span class="sr-only" role="status" aria-live="polite">{liveAnnouncement}</span>

  <footer class="transcript-foot">
    {#if footerNote}
      <p id="transcript-instructions" class="transcript-footnote">{footerNote}</p>
    {/if}

    {#if activePrompt && (anchorChips.length || discussChip)}
      <div class="chip-row">
        {#each anchorChips as option}
          <button
            type="button"
            class="chip"
            class:chip--pressed={pressedChip === option}
            disabled={disabled || pending || paused}
            aria-label={`Insert sentence starter: ${option}`}
            on:click={() => prefillChip(option)}
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
        bind:this={textareaEl}
        bind:value={draft}
        rows="3"
        disabled={disabled || pending || paused}
        class="transcript-textarea"
        placeholder={placeholder}
        aria-describedby={composerInstructionId || undefined}
        on:input={handleInput}
        on:keydown={handleKeydown}
      ></textarea>
      <button
        class="button-primary transcript-submit"
        disabled={disabled || pending || paused || !draft.trim()}
      >
        {#if pending}
          <span class="dot-pulse" aria-hidden="true"><span></span><span></span><span></span></span>
          <span>{submitLabel}</span>
        {:else}
          <span>{submitLabel}</span>
        {/if}
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

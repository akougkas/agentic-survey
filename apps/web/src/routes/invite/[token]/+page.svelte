<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import { demoCopy } from '$lib/demo-copy';
  import type { InviteInfoResponse, MicroFormField, RedeemInviteResponse } from '$lib/types';

  let info: InviteInfoResponse | null = null;
  let token = '';
  let loading = true;
  let error = '';
  let redeeming = false;
  let consentMode: 'anonymous' | 'named' = 'anonymous';
  let identityLabel = '';
  let microFormAnswers: Record<string, string> = {};

  $: token = $page.params.token ?? '';
  $: bundleInvite = $page.data.runtimeContext?.ui.invite ?? null;
  $: inviteCopy = {
    header_eyebrow: bundleInvite?.header_eyebrow ?? demoCopy.invite.header_eyebrow,
    header_wordmark: bundleInvite?.header_wordmark ?? demoCopy.invite.header_wordmark,
    header_subline: bundleInvite?.header_subline ?? demoCopy.invite.header_subline,
    page_title: bundleInvite?.page_title ?? demoCopy.invite.page_title,
    consent_title: bundleInvite?.consent_title ?? demoCopy.invite.consent_title,
    anonymous_title: bundleInvite?.anonymous_title ?? demoCopy.invite.anonymous_title,
    anonymous_description:
      bundleInvite?.anonymous_description ?? demoCopy.invite.anonymous_description,
    named_title: bundleInvite?.named_title ?? demoCopy.invite.named_title,
    named_description: bundleInvite?.named_description ?? demoCopy.invite.named_description,
    micro_form_eyebrow: bundleInvite?.micro_form_eyebrow ?? demoCopy.invite.micro_form_eyebrow,
    micro_form_description:
      bundleInvite?.micro_form_description ?? demoCopy.invite.micro_form_description,
    micro_form_required_hint:
      bundleInvite?.micro_form_required_hint ?? demoCopy.invite.micro_form_required_hint,
    micro_form_answer_note:
      bundleInvite?.micro_form_answer_note ?? demoCopy.invite.micro_form_answer_note,
    start_button_idle: bundleInvite?.start_button_idle ?? demoCopy.invite.start_button_idle,
    start_button_pending:
      bundleInvite?.start_button_pending ?? demoCopy.invite.start_button_pending,
    next_eyebrow: bundleInvite?.next_eyebrow ?? demoCopy.invite.next_eyebrow,
    next_steps:
      bundleInvite && bundleInvite.next_steps.length > 0
        ? bundleInvite.next_steps
        : [...demoCopy.invite.next_steps],
    closed_title: bundleInvite?.closed_title ?? demoCopy.invite.closed_title,
    closed_status_eyebrow:
      bundleInvite?.closed_status_eyebrow ?? demoCopy.invite.closed_status_eyebrow,
    closed_status_template:
      bundleInvite?.closed_status_template ?? demoCopy.invite.closed_status_template,
    closed_used_message:
      bundleInvite?.closed_used_message ?? demoCopy.invite.closed_used_message,
    closed_revoked_message:
      bundleInvite?.closed_revoked_message ?? demoCopy.invite.closed_revoked_message,
    closed_fresh_link_message:
      bundleInvite?.closed_fresh_link_message ?? demoCopy.invite.closed_fresh_link_message
  };
  $: inviteInactiveMessage =
    info?.status === 'used'
      ? inviteCopy.closed_used_message
      : info?.status === 'revoked'
        ? inviteCopy.closed_revoked_message
        : '';
  $: microFormFields = (info?.micro_form_schema ?? []).filter((field) => {
    if (field.field_type === 'single_select' && (field.options ?? []).length === 0) {
      console.warn(`Skipping single_select field '${field.key}' with no options.`);
      return false;
    }
    return true;
  });
  $: firstMissingRequiredKey = (() => {
    for (const field of microFormFields) {
      if (!field.required) continue;
      const value = (microFormAnswers[field.key] ?? '').trim();
      if (!value) return field.key;
    }
    return '';
  })();
  $: microFormComplete = firstMissingRequiredKey === '';

  onMount(async () => {
    try {
      info = await getJson<InviteInfoResponse>(`/invites/${encodeURIComponent(token)}`);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to look up this invite.';
    } finally {
      loading = false;
    }
  });

  function sanitizedAnswers(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const field of microFormFields) {
      const value = (microFormAnswers[field.key] ?? '').trim();
      if (value) out[field.key] = value;
    }
    return out;
  }

  async function redeem(): Promise<void> {
    if (!info || redeeming) {
      return;
    }

    redeeming = true;
    error = '';

    try {
      const result = await postJson<RedeemInviteResponse>(`/invites/${encodeURIComponent(token)}/redeem`, {
        consent_mode: consentMode,
        identity_label: consentMode === 'named' ? identityLabel.trim() : '',
        micro_form_answers: sanitizedAnswers()
      });
      await goto(`/chat/${result.session.id}`);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to start that session right now.';
    } finally {
      redeeming = false;
    }
  }
</script>

<svelte:head>
  <title>{inviteCopy.page_title}</title>
</svelte:head>

{#if inviteCopy.header_wordmark || inviteCopy.header_eyebrow || inviteCopy.header_subline}
  <header class="grid gap-1 pb-4">
    {#if inviteCopy.header_wordmark}
      <p class="font-display text-[1.2rem] tracking-[0.14em] text-moss">
        {inviteCopy.header_wordmark}
      </p>
    {/if}
    {#if inviteCopy.header_eyebrow}
      <p class="eyebrow">{inviteCopy.header_eyebrow}</p>
    {/if}
    {#if inviteCopy.header_subline}
      <p class="text-sm text-[color:var(--muted)]">{inviteCopy.header_subline}</p>
    {/if}
  </header>
{/if}

{#if loading}
  <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Looking up the invitation...</article>
{:else if !info}
  <article class="band px-6 py-6 text-sm text-ember">{error || 'Invitation not found.'}</article>
{:else if info.status !== 'active'}
  <section class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
    <article class="band grid gap-5 px-6 py-7 md:px-8">
      <div class="grid gap-3">
        <p class="eyebrow">{info.campaign_title}</p>
        <h2 class="section-title md:text-[2.8rem]">{inviteCopy.closed_title}</h2>
        <p class="section-copy">{inviteInactiveMessage}</p>
      </div>

      <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
        {inviteCopy.closed_fresh_link_message}
      </p>

      <a class="button-primary w-fit" href="/">Back to home</a>
    </article>

    <aside class="grid content-start gap-4">
      <section class="band-soft grid gap-3 px-5 py-5">
        <p class="eyebrow">{inviteCopy.closed_status_eyebrow}</p>
        <p class="m-0 text-sm leading-7 text-[color:var(--text)]">
          {inviteCopy.closed_status_template.replace('{status}', info.status)}
        </p>
      </section>
    </aside>
  </section>
{:else}
  <section class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
    <article class="band grid gap-6 px-6 py-7 md:px-8">
      <div class="grid gap-3">
        <p class="eyebrow">{info.campaign_title}</p>
        <h2 class="section-title md:text-[2.8rem]">{inviteCopy.consent_title}</h2>
        <p class="section-copy">{info.consent_language}</p>
      </div>

      <form class="grid gap-4" on:submit|preventDefault={redeem}>
        <label
          class={`rounded-[8px] px-5 py-5 transition ${
            consentMode === 'anonymous'
              ? 'bg-[color:rgba(126,184,141,0.08)] ring-1 ring-[color:rgba(126,184,141,0.36)]'
              : 'bg-[color:rgba(255,255,255,0.02)] ring-1 ring-[color:rgba(232,224,207,0.12)]'
          }`}
        >
          <div class="flex items-start gap-3">
            <input type="radio" class="sr-only" bind:group={consentMode} value="anonymous" />
            {#if consentMode === 'anonymous'}
              <svg aria-hidden="true" viewBox="0 0 20 20" class="mt-1 h-4 w-4 shrink-0 text-moss" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="10" cy="10" r="8.5" fill="rgba(126,184,141,0.16)" />
                <path d="M6.2 10.4l2.6 2.6 5-5.6" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            {:else}
              <span aria-hidden="true" class="mt-1 h-4 w-4 shrink-0 rounded-full border border-[color:rgba(232,224,207,0.28)]"></span>
            {/if}
            <div class="grid gap-2">
              <h3 class="font-display text-[1.7rem] leading-tight">{inviteCopy.anonymous_title}</h3>
              <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
                {inviteCopy.anonymous_description}
              </p>
            </div>
          </div>
        </label>

        <label
          class={`rounded-[8px] px-5 py-5 transition ${
            consentMode === 'named'
              ? 'bg-[color:rgba(126,184,141,0.08)] ring-1 ring-[color:rgba(126,184,141,0.36)]'
              : 'bg-[color:rgba(255,255,255,0.02)] ring-1 ring-[color:rgba(232,224,207,0.12)]'
          }`}
        >
          <div class="flex items-start gap-3">
            <input type="radio" class="sr-only" bind:group={consentMode} value="named" />
            {#if consentMode === 'named'}
              <svg aria-hidden="true" viewBox="0 0 20 20" class="mt-1 h-4 w-4 shrink-0 text-moss" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="10" cy="10" r="8.5" fill="rgba(126,184,141,0.16)" />
                <path d="M6.2 10.4l2.6 2.6 5-5.6" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            {:else}
              <span aria-hidden="true" class="mt-1 h-4 w-4 shrink-0 rounded-full border border-[color:rgba(232,224,207,0.28)]"></span>
            {/if}
            <div class="grid gap-3">
              <h3 class="font-display text-[1.7rem] leading-tight">{inviteCopy.named_title}</h3>
              <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
                {inviteCopy.named_description}
              </p>
              {#if consentMode === 'named'}
                <input
                  type="text"
                  bind:value={identityLabel}
                  placeholder="Name or preferred citation"
                  class="field"
                />
              {/if}
            </div>
          </div>
        </label>

        {#if microFormFields.length > 0}
          <div class="grid gap-1 border-t border-[color:var(--line)] pt-5">
            <p class="eyebrow">{inviteCopy.micro_form_eyebrow}</p>
            <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
              {inviteCopy.micro_form_description}
            </p>
          </div>

          <section class="grid gap-4">
            {#each microFormFields as field (field.key)}
              <div class="grid gap-2">
                <label class="label" for={`mf-${field.key}`}>
                  {field.label}{#if field.required}<span aria-hidden="true" class="ml-1 text-ember">*</span>{/if}
                </label>
                {#if field.field_type === 'long_text'}
                  <textarea
                    id={`mf-${field.key}`}
                    rows="5"
                    bind:value={microFormAnswers[field.key]}
                    class="field min-h-[8rem]"
                    required={field.required}
                  ></textarea>
                  <p class="m-0 text-xs text-[color:var(--muted)]">
                    {inviteCopy.micro_form_answer_note}
                  </p>
                {:else if field.field_type === 'single_select'}
                  <div class="grid gap-2">
                    {#each field.options ?? [] as option (option)}
                      {@const isSelected = microFormAnswers[field.key] === option}
                      <label
                        class={`flex items-start gap-3 rounded-[8px] px-4 py-3 transition ${
                          isSelected
                            ? 'bg-[color:rgba(126,184,141,0.08)] ring-1 ring-[color:rgba(126,184,141,0.36)]'
                            : 'bg-[color:rgba(255,255,255,0.02)] ring-1 ring-[color:rgba(232,224,207,0.12)]'
                        }`}
                      >
                        <input
                          type="radio"
                          class="sr-only"
                          name={`mf-${field.key}`}
                          value={option}
                          bind:group={microFormAnswers[field.key]}
                        />
                        {#if isSelected}
                          <svg aria-hidden="true" viewBox="0 0 20 20" class="mt-0.5 h-4 w-4 shrink-0 text-moss" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="10" cy="10" r="8.5" fill="rgba(126,184,141,0.16)" />
                            <path d="M6.2 10.4l2.6 2.6 5-5.6" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        {:else}
                          <span aria-hidden="true" class="mt-0.5 h-4 w-4 shrink-0 rounded-full border border-[color:rgba(232,224,207,0.28)]"></span>
                        {/if}
                        <span class="text-sm leading-6 text-[color:var(--text)]">{option}</span>
                      </label>
                    {/each}
                  </div>
                {:else}
                  <input
                    id={`mf-${field.key}`}
                    type="text"
                    bind:value={microFormAnswers[field.key]}
                    class="field"
                    required={field.required}
                  />
                {/if}
                {#if field.required && firstMissingRequiredKey === field.key}
                  <p class="m-0 text-xs text-[color:var(--muted)]">{inviteCopy.micro_form_required_hint}</p>
                {/if}
              </div>
            {/each}
          </section>
        {/if}

        {#if error}
          <p class="m-0 text-sm text-ember">{error}</p>
        {/if}

        <button
          class="button-primary w-full md:w-fit"
          disabled={redeeming || info.status !== 'active' || (consentMode === 'named' && !identityLabel.trim()) || !microFormComplete}
        >
          {redeeming ? inviteCopy.start_button_pending : inviteCopy.start_button_idle}
        </button>
      </form>
    </article>

    <aside class="grid content-start gap-4">
      <section class="band-soft grid gap-3 px-5 py-5">
        <p class="eyebrow">{inviteCopy.next_eyebrow}</p>
        <ol class="m-0 grid gap-3 pl-5 text-sm leading-7 text-[color:var(--text)]">
          {#each inviteCopy.next_steps as step}
            <li>{step}</li>
          {/each}
        </ol>
      </section>
    </aside>
  </section>
{/if}

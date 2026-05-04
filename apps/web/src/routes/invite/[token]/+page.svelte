<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import { runtimeCopy } from '$lib/runtime-copy';
  import type { InviteInfoResponse, RedeemInviteResponse } from '$lib/types';

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
    page_title: bundleInvite?.page_title ?? runtimeCopy.invite.page_title,
    consent_title: bundleInvite?.consent_title ?? runtimeCopy.invite.consent_title,
    anonymous_title: bundleInvite?.anonymous_title ?? runtimeCopy.invite.anonymous_title,
    anonymous_description:
      bundleInvite?.anonymous_description ?? runtimeCopy.invite.anonymous_description,
    named_title: bundleInvite?.named_title ?? runtimeCopy.invite.named_title,
    named_description: bundleInvite?.named_description ?? runtimeCopy.invite.named_description,
    micro_form_eyebrow: bundleInvite?.micro_form_eyebrow ?? runtimeCopy.invite.micro_form_eyebrow,
    micro_form_description:
      bundleInvite?.micro_form_description ?? runtimeCopy.invite.micro_form_description,
    micro_form_required_hint:
      bundleInvite?.micro_form_required_hint ?? runtimeCopy.invite.micro_form_required_hint,
    micro_form_answer_note:
      bundleInvite?.micro_form_answer_note ?? runtimeCopy.invite.micro_form_answer_note,
    start_button_idle: bundleInvite?.start_button_idle ?? runtimeCopy.invite.start_button_idle,
    start_button_pending:
      bundleInvite?.start_button_pending ?? runtimeCopy.invite.start_button_pending,
    next_eyebrow: bundleInvite?.next_eyebrow ?? runtimeCopy.invite.next_eyebrow,
    next_steps:
      bundleInvite && bundleInvite.next_steps.length > 0
        ? bundleInvite.next_steps
        : [...runtimeCopy.invite.next_steps],
    closed_title: bundleInvite?.closed_title ?? runtimeCopy.invite.closed_title,
    closed_status_eyebrow:
      bundleInvite?.closed_status_eyebrow ?? runtimeCopy.invite.closed_status_eyebrow,
    closed_status_template:
      bundleInvite?.closed_status_template ?? runtimeCopy.invite.closed_status_template,
    closed_used_message:
      bundleInvite?.closed_used_message ?? runtimeCopy.invite.closed_used_message,
    closed_revoked_message:
      bundleInvite?.closed_revoked_message ?? runtimeCopy.invite.closed_revoked_message,
    closed_fresh_link_message:
      bundleInvite?.closed_fresh_link_message ?? runtimeCopy.invite.closed_fresh_link_message
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

{#if loading}
  <article class="invite-loading">Looking up the invitation...</article>
{:else if !info}
  <article class="invite-error">{error || 'Invitation not found.'}</article>
{:else if info.status !== 'active'}
  <article class="invite-page invite-page--closed">
    <header class="invite-header">
      <p class="eyebrow">{info.campaign_title}</p>
      <h1 class="invite-title">{inviteCopy.closed_title}</h1>
    </header>

    <p class="invite-prose">{inviteInactiveMessage}</p>
    <p class="invite-meta">
      <span class="label">{inviteCopy.closed_status_eyebrow}:</span>
      <span>{inviteCopy.closed_status_template.replace('{status}', info.status)}</span>
    </p>
    <p class="invite-prose">{inviteCopy.closed_fresh_link_message}</p>
    <a class="button-primary w-fit" href="/">Back to home</a>
  </article>
{:else}
  <article class="invite-page">
    <header class="invite-header">
      <p class="eyebrow">{info.campaign_title}</p>
      <h1 class="invite-title">{inviteCopy.consent_title}</h1>
    </header>

    <p class="invite-prose">{info.consent_language}</p>

    <form class="invite-form" on:submit|preventDefault={redeem}>
      <fieldset class="consent-modes">
        <legend class="label consent-modes-legend">Choose how to contribute</legend>

        <label
          class="consent-card"
          class:consent-card--active={consentMode === 'anonymous'}
        >
          <input type="radio" bind:group={consentMode} value="anonymous" />
          <span class="consent-card-marker" aria-hidden="true"></span>
          <span class="consent-card-body">
            <span class="consent-card-title">{inviteCopy.anonymous_title}</span>
            <span class="consent-card-description">{inviteCopy.anonymous_description}</span>
          </span>
        </label>

        <label
          class="consent-card"
          class:consent-card--active={consentMode === 'named'}
        >
          <input type="radio" bind:group={consentMode} value="named" />
          <span class="consent-card-marker" aria-hidden="true"></span>
          <span class="consent-card-body">
            <span class="consent-card-title">{inviteCopy.named_title}</span>
            <span class="consent-card-description">{inviteCopy.named_description}</span>
            {#if consentMode === 'named'}
              <input
                type="text"
                bind:value={identityLabel}
                placeholder="Name or preferred citation"
                class="field consent-card-field"
                aria-label="Identity label"
              />
            {/if}
          </span>
        </label>
      </fieldset>

      {#if microFormFields.length > 0}
        <section class="micro-form">
          <header class="micro-form-header">
            <p class="eyebrow">{inviteCopy.micro_form_eyebrow}</p>
            <p class="invite-prose invite-prose--small">{inviteCopy.micro_form_description}</p>
          </header>

          {#each microFormFields as field (field.key)}
            <div class="micro-form-field">
              <label class="micro-form-label" for={`mf-${field.key}`}>
                {field.label}{#if field.required}<span aria-hidden="true" class="required-mark">*</span>{/if}
              </label>
              {#if field.field_type === 'long_text'}
                <textarea
                  id={`mf-${field.key}`}
                  rows="4"
                  bind:value={microFormAnswers[field.key]}
                  class="field min-h-[7rem]"
                  required={field.required}
                ></textarea>
                <p class="micro-form-note">{inviteCopy.micro_form_answer_note}</p>
              {:else if field.field_type === 'single_select'}
                <div class="grid gap-2">
                  {#each field.options ?? [] as option (option)}
                    {@const isSelected = microFormAnswers[field.key] === option}
                    <label class="select-row" class:select-row--active={isSelected}>
                      <input
                        type="radio"
                        name={`mf-${field.key}`}
                        value={option}
                        bind:group={microFormAnswers[field.key]}
                      />
                      <span class="consent-card-marker" aria-hidden="true"></span>
                      <span class="select-row-text">{option}</span>
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
                <p class="micro-form-note">{inviteCopy.micro_form_required_hint}</p>
              {/if}
            </div>
          {/each}
        </section>
      {/if}

      {#if error}
        <p class="invite-error-inline">{error}</p>
      {/if}

      <button
        class="button-primary invite-submit"
        disabled={redeeming || info.status !== 'active' || (consentMode === 'named' && !identityLabel.trim()) || !microFormComplete}
      >
        {redeeming ? inviteCopy.start_button_pending : inviteCopy.start_button_idle}
      </button>
    </form>

    <aside class="invite-runs">
      <p class="eyebrow">{inviteCopy.next_eyebrow}</p>
      <ol class="invite-runs-list">
        {#each inviteCopy.next_steps as step}
          <li>{step}</li>
        {/each}
      </ol>
    </aside>
  </article>
{/if}

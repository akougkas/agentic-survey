<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, postJson } from '$lib/api';
  import { demoCopy } from '$lib/demo-copy';
  import type { InviteInfoResponse, RedeemInviteResponse } from '$lib/types';

  let info: InviteInfoResponse | null = null;
  let token = '';
  let loading = true;
  let error = '';
  let redeeming = false;
  let consentMode: 'anonymous' | 'named' = 'anonymous';
  let identityLabel = '';

  $: token = $page.params.token ?? '';
  $: inviteInactiveMessage = info?.status === 'used'
    ? demoCopy.invite.usedMessage
    : info?.status === 'revoked'
      ? demoCopy.invite.revokedMessage
      : '';

  onMount(async () => {
    try {
      info = await getJson<InviteInfoResponse>(`/invites/${encodeURIComponent(token)}`);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to look up this invite.';
    } finally {
      loading = false;
    }
  });

  async function redeem(): Promise<void> {
    if (!info || redeeming) {
      return;
    }

    redeeming = true;
    error = '';

    try {
      const result = await postJson<RedeemInviteResponse>(`/invites/${encodeURIComponent(token)}/redeem`, {
        consent_mode: consentMode,
        identity_label: consentMode === 'named' ? identityLabel.trim() : ''
      });
      await goto(`/chat/${result.session.id}`);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to start that session right now.';
    } finally {
      redeeming = false;
    }
  }
</script>

{#if loading}
  <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Looking up the invitation...</article>
{:else if !info}
  <article class="band px-6 py-6 text-sm text-ember">{error || 'Invitation not found.'}</article>
{:else if info.status !== 'active'}
  <section class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
    <article class="band grid gap-5 px-6 py-7 md:px-8">
      <div class="grid gap-3">
        <p class="eyebrow">{info.campaign_title}</p>
        <h2 class="section-title md:text-[2.8rem]">{demoCopy.invite.closedTitle}</h2>
        <p class="section-copy">{inviteInactiveMessage}</p>
      </div>

      <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
        {demoCopy.invite.freshLinkMessage}
      </p>

      <a class="button-primary w-fit" href="/">Back to home</a>
    </article>

    <aside class="grid content-start gap-4">
      <section class="band-soft grid gap-3 px-5 py-5">
        <p class="eyebrow">{demoCopy.invite.statusEyebrow}</p>
        <p class="m-0 text-sm leading-7 text-[color:var(--text)]">
          {demoCopy.invite.statusTemplate.replace('{status}', info.status)}
        </p>
      </section>
    </aside>
  </section>
{:else}
  <section class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
    <article class="band grid gap-6 px-6 py-7 md:px-8">
      <div class="grid gap-3">
        <p class="eyebrow">{info.campaign_title}</p>
        <h2 class="section-title md:text-[2.8rem]">{demoCopy.invite.consentTitle}</h2>
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
            <input type="radio" bind:group={consentMode} value="anonymous" />
            <div class="grid gap-2">
              <h3 class="font-display text-[1.7rem] leading-tight">{demoCopy.invite.anonymousTitle}</h3>
              <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
                {demoCopy.invite.anonymousDescription}
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
            <input type="radio" bind:group={consentMode} value="named" />
            <div class="grid gap-3">
              <h3 class="font-display text-[1.7rem] leading-tight">{demoCopy.invite.namedTitle}</h3>
              <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">
                {demoCopy.invite.namedDescription}
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

        {#if error}
          <p class="m-0 text-sm text-ember">{error}</p>
        {/if}

        <button
          class="button-primary w-fit"
          disabled={redeeming || info.status !== 'active' || (consentMode === 'named' && !identityLabel.trim())}
        >
          {redeeming ? 'Starting session...' : demoCopy.invite.enterConversationLabel}
        </button>
      </form>
    </article>

    <aside class="grid content-start gap-4">
      <section class="band-soft grid gap-3 px-5 py-5">
        <p class="eyebrow">{demoCopy.invite.nextEyebrow}</p>
        <ol class="m-0 grid gap-3 pl-5 text-sm leading-7 text-[color:var(--text)]">
          {#each demoCopy.invite.nextSteps as step}
            <li>{step}</li>
          {/each}
        </ol>
      </section>
    </aside>
  </section>
{/if}

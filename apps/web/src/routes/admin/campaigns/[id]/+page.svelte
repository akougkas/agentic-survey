<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';

  import { ApiError, getJson, patchJson, postJson } from '$lib/api';
  import {
    campaignSourceLabel,
    campaignStateLabel,
    campaignStateTone,
    changedSectionLabel,
    formatTimestamp,
    inviteStatusTone,
    readinessTone,
  } from '$lib/campaign-ui';
  import { getAdminSession } from '$lib/admin';
  import ChatPane from '$lib/components/ChatPane.svelte';
  import { demoCopy } from '$lib/demo-copy';
  import { getModelCatalog } from '$lib/runtime';
  import type {
    AgentRole,
    Campaign,
    CampaignBundleResponse,
    CampaignState,
    CatalogEntry,
    Invite,
    InterviewSessionRecord,
    OutlineRevision,
  } from '$lib/types';

  const transitionLabels: Partial<Record<CampaignState, string>> = {
    reviewing: 'Move to review',
    live: 'Go live',
    monitoring: 'Move to monitoring',
    closing: 'Start closing',
    archived: 'Archive',
  };

  let bundle: CampaignBundleResponse | null = null;
  let campaignId = '';
  let loading = true;
  let sendPending = false;
  let advancePending = false;
  let invitePending = false;
  let error = '';
  let inviteLabel = '';
  let inviteBaseOrigin = '';
  let revokingInviteId = '';
  let chatterCatalog: CatalogEntry[] = [];
  let scientistCatalog: CatalogEntry[] = [];
  let modelPendingRole: AgentRole | '' = '';

  $: runtimeContext = $page.data.runtimeContext ?? null;
  $: campaignId = $page.params.id ?? '';
  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;
  $: showDesignerChat =
    bundle !== null &&
    bundle.campaign.source === 'blank' &&
    (bundle.campaign.state === 'draft' || bundle.campaign.state === 'designing');
  $: visibleRevisions = bundle ? [...bundle.outline_revisions].reverse() : [];
  $: latestRevision = visibleRevisions[0] ?? null;
  $: defaultChatterEntry = chatterCatalog.find((entry) => entry.is_default) ?? chatterCatalog[0] ?? null;
  $: defaultScientistEntry = scientistCatalog.find((entry) => entry.is_default) ?? scientistCatalog[0] ?? null;
  $: canCreateInvites =
    bundle !== null &&
    (bundle.campaign.state === 'reviewing' ||
      bundle.campaign.state === 'live' ||
      bundle.campaign.state === 'monitoring');
  $: invitesRedeemable =
    bundle !== null && (bundle.campaign.state === 'live' || bundle.campaign.state === 'monitoring');

  onMount(async () => {
    inviteBaseOrigin = typeof window === 'undefined' ? '' : window.location.origin;
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      await Promise.all([loadModelCatalogs(), loadCampaign()]);
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to load the campaign.';
      loading = false;
    }
  });

  async function loadModelCatalogs(): Promise<void> {
    [chatterCatalog, scientistCatalog] = await Promise.all([
      getModelCatalog('chatter'),
      getModelCatalog('scientist')
    ]);
  }

  async function loadCampaign(): Promise<void> {
    loading = true;
    error = '';

    try {
      bundle = await getJson<CampaignBundleResponse>(`/campaigns/${campaignId}`);
      if (!bundle.designer_session && bundle.campaign.source === 'blank' && bundle.campaign.state === 'draft') {
        bundle = await postJson<CampaignBundleResponse>(`/campaigns/${campaignId}/designer/start`, {});
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to load the campaign.';
    } finally {
      loading = false;
    }
  }

  async function submitTurn(event: CustomEvent<{ content: string }>): Promise<void> {
    if (!bundle) return;
    sendPending = true;
    error = '';
    try {
      bundle = await postJson<CampaignBundleResponse>(`/campaigns/${campaignId}/designer/turns`, {
        content: event.detail.content,
      });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to send that turn right now.';
    } finally {
      sendPending = false;
    }
  }

  async function advanceTo(target: CampaignState): Promise<void> {
    advancePending = true;
    error = '';
    try {
      bundle = await postJson<CampaignBundleResponse>(`/campaigns/${campaignId}/advance`, {
        target_state: target,
      });
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : `Unable to advance to ${target}.`;
    } finally {
      advancePending = false;
    }
  }

  async function createInvite(): Promise<void> {
    if (!bundle || !canCreateInvites) return;
    invitePending = true;
    error = '';
    try {
      const invite = await postJson<Invite>('/invites', {
        campaign_id: campaignId,
        label: inviteLabel.trim(),
      });
      const existing = bundle.invites ?? [];
      bundle = { ...bundle, invites: [...existing, invite] };
      inviteLabel = '';
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to create that invite.';
    } finally {
      invitePending = false;
    }
  }

  async function revokeInvite(inviteId: string): Promise<void> {
    if (!bundle) return;
    revokingInviteId = inviteId;
    error = '';
    try {
      const revoked = await postJson<Invite>(`/invites/${inviteId}/revoke`, {});
      bundle = {
        ...bundle,
        invites: (bundle.invites ?? []).map((invite) => (invite.id === inviteId ? revoked : invite)),
      };
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to revoke that invite.';
    } finally {
      revokingInviteId = '';
    }
  }

  function inviteUrl(invite: Invite): string {
    return `${inviteBaseOrigin}/invite/${invite.token}`;
  }

  function sessionSummary(session: InterviewSessionRecord): string {
    const identity = session.identity_label ? ` · ${session.identity_label}` : '';
    return `${session.turns.length} turns · ${session.status}${identity}`;
  }

  function transitionLabel(state: CampaignState): string {
    return transitionLabels[state] ?? `Move to ${campaignStateLabel(state).toLowerCase()}`;
  }

  function revisionSummary(revision: OutlineRevision): string {
    return revision.summary || 'Outline updated.';
  }

  function currentModelSelection(role: AgentRole): string {
    return bundle?.campaign.agent_models?.[role] ?? '';
  }

  function modelRouteLabel(role: AgentRole): string {
    return bundle?.campaign.agent_models?.[role] ? 'Campaign override' : 'Role default';
  }

  async function updateCampaignModel(role: AgentRole, catalogId: string): Promise<void> {
    if (!bundle) return;

    const previousModels = bundle.campaign.agent_models ? { ...bundle.campaign.agent_models } : null;
    const nextModels = { ...(previousModels ?? {}) };
    if (catalogId) {
      nextModels[role] = catalogId;
    } else {
      delete nextModels[role];
    }

    bundle = {
      ...bundle,
      campaign: {
        ...bundle.campaign,
        agent_models: Object.keys(nextModels).length > 0 ? nextModels : null
      }
    };

    modelPendingRole = role;
    error = '';
    try {
      const campaign = await patchJson<Campaign>(`/campaigns/${campaignId}/models`, {
        [role]: catalogId || null
      });
      bundle = { ...bundle, campaign };
    } catch (caught) {
      bundle = {
        ...bundle,
        campaign: {
          ...bundle.campaign,
          agent_models: previousModels
        }
      };
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to update that model route.';
    } finally {
      modelPendingRole = '';
    }
  }
</script>

<section class="grid gap-5">
  <a class="text-sm text-moss" href="/admin/campaigns">&larr; {demoCopy.campaigns.detailBackLabel}</a>

  {#if loading}
    <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Loading campaign...</article>
  {:else if error && !bundle}
    <article class="band px-6 py-6 text-sm text-ember">{error}</article>
  {:else if bundle}
    <section class="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_24rem]">
      <div class="grid gap-6">
        {#if showDesignerChat}
          <ChatPane
            title={demoCopy.campaigns.designerTitle}
            messages={bundle.designer_session?.turns ?? []}
            agentName="Mira"
            participantName="Operator"
            placeholder="Add the next constraint, participant signal, or blind spot."
            submitLabel="Continue design"
            pending={sendPending}
            footerNote={demoCopy.campaigns.designerFooter}
            on:submit={submitTurn}
          />
        {:else}
          <section class="band grid gap-5 px-6 py-6">
            <div class="grid gap-2">
              <p class="eyebrow">{demoCopy.campaigns.revisionsEyebrow}</p>
              <h2 class="section-title">
                {bundle.campaign.source === 'seed' ? 'Seed-backed launch path' : 'Designer transcript'}
              </h2>
              <p class="section-copy">
                {bundle.campaign.source === 'seed'
                  ? demoCopy.campaigns.seededReadyMessage
                  : 'The draft is already past the design loop. Review the latest operator-designer exchange here without leaving the campaign page.'}
              </p>
            </div>

            {#if bundle.designer_session?.turns?.length}
              <div class="stack-list border-t border-[color:var(--line)]">
                {#each [...bundle.designer_session.turns].slice(-6) as turn}
                  <article class="stack-row">
                    <p class="label m-0">{turn.role === 'designer' ? 'Mira' : 'Operator'}</p>
                    <p class="m-0 text-sm leading-7 text-[color:var(--text)]">{turn.content}</p>
                  </article>
                {/each}
              </div>
            {:else}
              <p class="m-0 border-t border-[color:var(--line)] pt-4 text-sm leading-7 text-[color:var(--muted)]">
                {demoCopy.campaigns.seededReadyMessage}
              </p>
            {/if}
          </section>
        {/if}

        <section class="band grid gap-5 px-6 py-6">
          <div class="grid gap-2">
            <p class="eyebrow">{demoCopy.campaigns.revisionsEyebrow}</p>
            <h2 class="section-title">{demoCopy.campaigns.revisionsTitle}</h2>
          </div>

          {#if visibleRevisions.length > 0}
            <div class="stack-list border-t border-[color:var(--line)]">
              {#each visibleRevisions as revision}
                <article class="stack-row">
                  <div class="flex flex-wrap items-start justify-between gap-3">
                    <div class="grid gap-2">
                      <div class="chip-list">
                        <span class="status-badge" data-tone={revision.source === 'designer' ? 'moss' : 'neutral'}>
                          {revision.source}
                        </span>
                        {#each revision.changed_sections as changed}
                          <span class="chip">{changedSectionLabel(changed)}</span>
                        {/each}
                      </div>
                      <p class="m-0 text-sm leading-7 text-[color:var(--text)]">{revisionSummary(revision)}</p>
                    </div>
                    <p class="label m-0">{formatTimestamp(revision.created_at)}</p>
                  </div>
                </article>
              {/each}
            </div>
          {:else}
            <p class="m-0 text-sm text-[color:var(--muted)]">No outline revisions yet.</p>
          {/if}
        </section>

        <section class="band grid gap-5 px-6 py-6">
          <div class="grid gap-2">
            <p class="eyebrow">{demoCopy.campaigns.outlineEyebrow}</p>
            <h2 class="section-title">{demoCopy.campaigns.outlineTitle}</h2>
          </div>

          <div class="grid gap-5 border-t border-[color:var(--line)] pt-4 text-sm leading-7 text-[color:var(--muted)]">
            <div class="grid gap-2">
              <p class="label m-0">Summary</p>
              <p class="m-0 text-[color:var(--text)]">
                {bundle.campaign.outline.scientist_summary || demoCopy.campaigns.noSummaryYet}
              </p>
            </div>

            <div class="grid gap-2">
              <p class="label m-0">Objectives</p>
              <ul class="m-0 grid gap-2 pl-4 text-[color:var(--text)]">
                {#each bundle.campaign.outline.objectives as objective}
                  <li>{objective}</li>
                {/each}
              </ul>
            </div>

            <div class="grid gap-2">
              <p class="label m-0">Probes</p>
              <ul class="m-0 grid gap-2 pl-4 text-[color:var(--text)]">
                {#each bundle.campaign.outline.probes as probe}
                  <li>{probe}</li>
                {/each}
              </ul>
            </div>

            <div class="grid gap-2 md:grid-cols-2">
              <div class="grid gap-2">
                <p class="label m-0">Freshness query</p>
                <p class="m-0 text-[color:var(--text)]">{bundle.campaign.outline.freshness_query}</p>
              </div>

              <div class="grid gap-2">
                <p class="label m-0">Sample bounds</p>
                <p class="m-0 text-[color:var(--text)]">{bundle.campaign.min_n} to {bundle.campaign.max_n}</p>
              </div>
            </div>

            <div class="grid gap-2 md:grid-cols-2">
              <div class="grid gap-2">
                <p class="label m-0">Persona</p>
                <p class="m-0 text-[color:var(--text)]">
                  {bundle.campaign.outline.persona_hints.name}: {bundle.campaign.outline.persona_hints.tone}
                </p>
              </div>

              <div class="grid gap-2">
                <p class="label m-0">Participant fields</p>
                <div class="chip-list">
                  {#each bundle.campaign.outline.micro_form_schema as field}
                    <span class="chip">{field.label}</span>
                  {/each}
                </div>
              </div>
            </div>

            <div class="grid gap-2">
              <p class="label m-0">Consent</p>
              <p class="m-0 text-[color:var(--text)]">{bundle.campaign.outline.consent_language}</p>
            </div>
          </div>
        </section>
      </div>

      <aside class="grid content-start gap-4">
        <section class="band grid gap-5 px-6 py-6">
          <div class="grid gap-3">
            <div class="flex flex-wrap items-center gap-2">
              <span class="status-badge" data-tone="neutral">{campaignSourceLabel(bundle.campaign.source)}</span>
              <span class="status-badge" data-tone={campaignStateTone(bundle.campaign.state)}>
                {campaignStateLabel(bundle.campaign.state)}
              </span>
            </div>
            <div class="grid gap-2">
              <p class="eyebrow">{demoCopy.campaigns.workflowEyebrow}</p>
              <h2 class="section-title text-[1.9rem] md:text-[2.2rem]">{bundle.campaign.title}</h2>
              <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{demoCopy.campaigns.workflowTitle}</p>
            </div>
          </div>

          <div class="metric-grid border-t border-[color:var(--line)] pt-4 md:grid-cols-2 xl:grid-cols-2">
            <article class="metric-card">
              <p class="label m-0">Invites</p>
              <p class="m-0 text-lg text-[color:var(--text)]">{bundle.metrics.invite_count}</p>
            </article>
            <article class="metric-card">
              <p class="label m-0">Sessions</p>
              <p class="m-0 text-lg text-[color:var(--text)]">{bundle.metrics.session_count}</p>
            </article>
            <article class="metric-card">
              <p class="label m-0">Active invites</p>
              <p class="m-0 text-lg text-[color:var(--text)]">{bundle.metrics.active_invite_count}</p>
            </article>
            <article class="metric-card">
              <p class="label m-0">Active sessions</p>
              <p class="m-0 text-lg text-[color:var(--text)]">{bundle.metrics.active_session_count}</p>
            </article>
          </div>

          {#if latestRevision}
            <div class="grid gap-2 border-t border-[color:var(--line)] pt-4">
              <p class="label m-0">Latest outline change</p>
              <p class="m-0 text-sm leading-7 text-[color:var(--text)]">{latestRevision.summary}</p>
              <p class="m-0 text-xs text-[color:var(--muted)]">{formatTimestamp(latestRevision.created_at)}</p>
            </div>
          {/if}

          <div class="grid gap-2 border-t border-[color:var(--line)] pt-4">
            {#if bundle.next_states.length > 0}
              <div class="flex flex-wrap gap-2">
                {#each bundle.next_states as nextState}
                  <button
                    class={nextState === 'closing' ? 'button-danger' : 'button-primary'}
                    disabled={advancePending}
                    on:click={() => advanceTo(nextState)}
                  >
                    {transitionLabel(nextState)}
                  </button>
                {/each}
              </div>
            {:else}
              <p class="m-0 text-sm text-[color:var(--muted)]">{demoCopy.campaigns.reviewBlockedMessage}</p>
            {/if}
          </div>
        </section>

        <section class="band grid gap-5 px-6 py-6">
          <div class="grid gap-2">
            <p class="eyebrow">Model routing</p>
            <h3 class="font-display text-[1.65rem] leading-tight">Campaign model picks</h3>
          </div>

          <div class="grid gap-4 border-t border-[color:var(--line)] pt-4">
            <label class="grid gap-2">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="label">Chatter</span>
                <span class="status-badge" data-tone={currentModelSelection('chatter') ? 'moss' : 'neutral'}>
                  {modelRouteLabel('chatter')}
                </span>
              </div>
              <select
                class="field"
                value={currentModelSelection('chatter')}
                disabled={modelPendingRole === 'chatter'}
                on:change={(event) =>
                  updateCampaignModel('chatter', (event.currentTarget as HTMLSelectElement).value)}
              >
                <option value="">Role default · {defaultChatterEntry?.label ?? 'Unavailable'}</option>
                {#if currentModelSelection('chatter') && !chatterCatalog.find((entry) => entry.catalog_id === currentModelSelection('chatter'))}
                  <option value={currentModelSelection('chatter')}>
                    Missing override · {currentModelSelection('chatter')}
                  </option>
                {/if}
                {#each chatterCatalog as entry}
                  <option value={entry.catalog_id}>{entry.label}</option>
                {/each}
              </select>
            </label>

            <label class="grid gap-2">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="label">Scientist</span>
                <span class="status-badge" data-tone={currentModelSelection('scientist') ? 'moss' : 'neutral'}>
                  {modelRouteLabel('scientist')}
                </span>
              </div>
              <select
                class="field"
                value={currentModelSelection('scientist')}
                disabled={modelPendingRole === 'scientist'}
                on:change={(event) =>
                  updateCampaignModel('scientist', (event.currentTarget as HTMLSelectElement).value)}
              >
                <option value="">Role default · {defaultScientistEntry?.label ?? 'Unavailable'}</option>
                {#if currentModelSelection('scientist') && !scientistCatalog.find((entry) => entry.catalog_id === currentModelSelection('scientist'))}
                  <option value={currentModelSelection('scientist')}>
                    Missing override · {currentModelSelection('scientist')}
                  </option>
                {/if}
                {#each scientistCatalog as entry}
                  <option value={entry.catalog_id}>{entry.label}</option>
                {/each}
              </select>
            </label>
          </div>
        </section>

        <section class="band grid gap-5 px-6 py-6">
          <div class="grid gap-2">
            <p class="eyebrow">{demoCopy.campaigns.readinessEyebrow}</p>
            <h3 class="font-display text-[1.65rem] leading-tight">{demoCopy.campaigns.readinessTitle}</h3>
          </div>

          <div class="grid gap-3 border-t border-[color:var(--line)] pt-4">
            <p class="m-0 text-sm text-[color:var(--muted)]">
              {bundle.readiness.completed}/{bundle.readiness.total} checks completed.
            </p>
            {#each bundle.readiness.checks as check}
              <article class="grid gap-2 rounded-[8px] border border-[color:var(--line)] px-4 py-4">
                <div class="flex items-center justify-between gap-3">
                  <p class="label m-0">{check.label}</p>
                  <span class="status-badge" data-tone={readinessTone(check)}>
                    {check.ready ? 'Ready' : 'Needs work'}
                  </span>
                </div>
                <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{check.detail}</p>
              </article>
            {/each}
          </div>
        </section>

        <section class="band grid gap-5 px-6 py-6">
          <div class="grid gap-2">
            <p class="eyebrow">{demoCopy.campaigns.invitesEyebrow}</p>
            <h3 class="font-display text-[1.65rem] leading-tight">{demoCopy.campaigns.invitesTitle}</h3>
          </div>

          <form class="grid gap-3 md:grid-cols-[1fr_auto]" on:submit|preventDefault={createInvite}>
            <input
              type="text"
              bind:value={inviteLabel}
              placeholder="Label (for example, pilot-01)"
              class="field"
            />
            <button class="button-primary" disabled={invitePending || !canCreateInvites}>
              {invitePending ? 'Creating...' : demoCopy.campaigns.createInviteLabel}
            </button>
          </form>

          <p class="m-0 text-sm text-[color:var(--muted)]">
            {invitesRedeemable ? demoCopy.campaigns.liveInviteHint : demoCopy.campaigns.reviewingInviteHint}
          </p>

          {#if bundle.invites && bundle.invites.length > 0}
            <div class="stack-list border-t border-[color:var(--line)]">
              {#each bundle.invites as invite}
                <div class="stack-row">
                  <div class="flex items-start justify-between gap-3">
                    <div class="grid gap-2">
                      <div class="flex flex-wrap items-center gap-2">
                        <p class="label m-0">{invite.label || invite.id}</p>
                        <span class="status-badge" data-tone={inviteStatusTone(invite.status)}>{invite.status}</span>
                      </div>
                      <a
                        class="m-0 break-all text-xs leading-6 text-moss"
                        href={inviteUrl(invite)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {inviteUrl(invite)}
                      </a>
                      {#if invite.session_id}
                        <a class="text-xs text-moss" href={`/admin/campaigns/${campaignId}/sessions/${invite.session_id}`}>
                          {demoCopy.campaigns.openTranscriptLabel}
                        </a>
                      {/if}
                    </div>
                    {#if invite.status === 'active'}
                      <button
                        class="button-secondary"
                        type="button"
                        disabled={revokingInviteId === invite.id}
                        on:click={() => revokeInvite(invite.id)}
                      >
                        {revokingInviteId === invite.id ? 'Revoking...' : demoCopy.campaigns.revokeInviteLabel}
                      </button>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <p class="m-0 text-sm text-[color:var(--muted)]">{demoCopy.campaigns.emptyInvites}</p>
          {/if}
        </section>

        <section class="band grid gap-4 px-6 py-6">
          <div class="grid gap-2">
            <p class="eyebrow">{demoCopy.campaigns.sessionsEyebrow}</p>
            <h3 class="font-display text-[1.65rem] leading-tight">{demoCopy.campaigns.sessionsTitle}</h3>
          </div>

          {#if bundle.sessions && bundle.sessions.length > 0}
            <div class="stack-list border-t border-[color:var(--line)]">
              {#each bundle.sessions as session}
                <div class="stack-row">
                  <div class="flex items-center justify-between gap-3">
                    <div class="flex flex-wrap items-center gap-2">
                      <p class="label m-0">{session.id}</p>
                      <span class="status-badge" data-tone={session.status === 'finished' ? 'brass' : 'moss'}>
                        {session.status}
                      </span>
                    </div>
                    <a class="text-xs text-moss" href={`/admin/campaigns/${campaignId}/sessions/${session.id}`}>
                      {demoCopy.campaigns.openTranscriptLabel}
                    </a>
                  </div>
                  <p class="m-0 text-sm leading-7 text-[color:var(--muted)]">{sessionSummary(session)}</p>
                </div>
              {/each}
            </div>
          {:else}
            <p class="m-0 text-sm text-[color:var(--muted)]">{demoCopy.campaigns.emptySessions}</p>
          {/if}
        </section>

        {#if error}
          <section class="px-1 text-sm text-ember">{error}</section>
        {/if}
      </aside>
    </section>
  {/if}
</section>

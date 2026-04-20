import type {
  CampaignOverviewItem,
  CampaignState,
  Invite,
  OutlineReadinessCheck,
} from '$lib/types';

type Tone = 'neutral' | 'moss' | 'ember' | 'brass';

const timestampFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

export function campaignStateLabel(state: CampaignState): string {
  const labels: Record<CampaignState, string> = {
    draft: 'Draft',
    designing: 'Designing',
    reviewing: 'Reviewing',
    live: 'Live',
    monitoring: 'Monitoring',
    closing: 'Closing',
    archived: 'Archived',
  };
  return labels[state];
}

export function campaignStateTone(state: CampaignState): Tone {
  if (state === 'live' || state === 'monitoring') return 'moss';
  if (state === 'reviewing' || state === 'closing') return 'brass';
  if (state === 'archived') return 'neutral';
  return 'ember';
}

export function campaignSourceLabel(source: 'blank' | 'seed'): string {
  return source === 'seed' ? 'Seed-backed' : 'Blank draft';
}

export function inviteStatusTone(status: Invite['status']): Tone {
  if (status === 'active') return 'moss';
  if (status === 'used') return 'brass';
  return 'ember';
}

export function changedSectionLabel(section: string): string {
  const labels: Record<string, string> = {
    initial_outline: 'Initial outline',
    scientist_summary: 'Brief summary',
    objectives: 'Objectives',
    probes: 'Interview probes',
    freshness_query: 'Freshness query',
    consent_language: 'Consent guidance',
    persona_hints: 'Persona',
    micro_form_schema: 'Participant fields',
    rubric: 'Rubric',
    review_status: 'Readiness',
  };
  return labels[section] ?? section.replaceAll('_', ' ');
}

export function readinessTone(check: OutlineReadinessCheck): Tone {
  return check.ready ? 'moss' : 'ember';
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Unknown time';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return timestampFormatter.format(parsed);
}

export function campaignActivityLabel(item: CampaignOverviewItem): string {
  const revisionTime = item.latest_outline_revision?.created_at;
  const sessionTime = item.designer_session?.updated_at;
  const latest = [revisionTime, sessionTime, item.campaign.updated_at].filter(Boolean).sort().at(-1);
  return formatTimestamp(latest);
}

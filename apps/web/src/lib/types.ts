export type CampaignState =
  | 'draft'
  | 'designing'
  | 'reviewing'
  | 'live'
  | 'monitoring'
  | 'closing'
  | 'archived';

export type AgentRole = 'chatter' | 'scientist' | 'validator' | 'analyst' | 'embedding' | 'ingest';
export type Endpoint = 'mini' | 'dynamo';
export type AgentModelSelections = Partial<Record<AgentRole, string>>;

export interface CatalogEntry {
  catalog_id: string;
  role: AgentRole;
  endpoint: Endpoint;
  model_id: string;
  label: string;
  notes?: string | null;
  enabled: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface CatalogEntryPayload {
  catalog_id: string;
  role: AgentRole;
  endpoint: Endpoint;
  model_id: string;
  label: string;
  notes?: string | null;
  enabled: boolean;
  is_default: boolean;
}

export interface MicroFormField {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
}

export type ParticipantControl = 'pause' | 'skip' | 'continue' | 'stop';

export interface ParticipantFAQEntry {
  key: string;
  question: string;
  answer: string;
  tags: string[];
}

export interface GetUserInputPayload {
  question: string;
  options: string[];
  allow_free_text: boolean;
  participant_controls: ParticipantControl[];
  suggested_control: ParticipantControl | null;
  sensitive_turn: boolean;
}

export interface BrainIntentRecord {
  response_mode: 'probe' | 'faq' | 'advice_refusal' | 'closing';
  question_intent: string;
  faq_key: string | null;
  shared_context_used: string[];
  should_close: boolean;
  close_reason: string;
  get_user_input: GetUserInputPayload | null;
}

export interface OutlineRubric {
  coverage_dimensions: string[];
  risk_checks: string[];
}

export interface OutlineArtifact {
  objectives: string[];
  probes: string[];
  rubric: OutlineRubric;
  min_n: number;
  max_n: number;
  freshness_query: string;
  persona_hints: Record<string, string>;
  consent_language: string;
  micro_form_schema: MicroFormField[];
  scientist_summary: string;
  study_context: string;
  market_context: string;
  technical_context: string;
  aggregate_graph_context: string;
  participant_faq: ParticipantFAQEntry[];
}

export interface GetUserInputOptions {
  question: string;
  options: string[];
  allow_free_text: boolean;
}

export interface RiskEntry {
  risk: string;
  mitigation: string;
}

export interface DecisionGate {
  gate: string;
  rationale: string;
}

export interface OutlineArtifactV2 {
  research_question: string;
  sampling_frame: string;
  exclusion_criteria: string;
  publication_intent: string;
  axes: string[];
  probes: string[];
  risk_register: RiskEntry[];
  grounding_sources_approved: string[];
  readiness_rationale: string;
  decision_gate: DecisionGate | null;
  suggested_search_queries: string[];
  min_n: number;
  max_n: number;
  objectives: string[];
  rubric: OutlineRubric | null;
  freshness_query: string;
  persona_hints: Record<string, string>;
  consent_language: string;
  micro_form_schema: MicroFormField[];
  scientist_summary: string;
  study_context: string;
  market_context: string;
  technical_context: string;
  aggregate_graph_context: string;
  participant_faq: ParticipantFAQEntry[];
}

export type OutlinePatchOp = 'replace' | 'append' | 'remove';

export interface OutlinePatchSection {
  section: string;
  op: OutlinePatchOp;
  value: unknown;
}

export interface OutlinePatch {
  sections: OutlinePatchSection[];
  provenance: string;
  summary: string;
}

export interface AxisCoverage {
  axis: string;
  score: number;
  gap: string;
}

export interface BrainBIntent {
  active_axis: string;
  axes_coverage: AxisCoverage[];
  question_intent: string;
  get_user_input: GetUserInputOptions;
  outline_patch: OutlinePatch | null;
  ready_for_review: boolean;
  should_close: boolean;
  closing: boolean;
  retrieval_used: boolean;
  retrieval_chunks: string[];
}

export interface BundleBranding {
  eyebrow: string;
  title: string;
  description: string;
}

export interface BundleHomeCopy {
  eyebrow: string;
  operator_path_label: string;
  operator_path_title: string;
  operator_path_description: string;
  participant_path_label: string;
  participant_path_title: string;
  participant_path_description: string;
  bundle_panel_title: string;
  persona_panel_title: string;
  persona_panel_description: string;
}

export interface BundleAdminCopy {
  nav_label: string;
  workspace_eyebrow: string;
  workspace_title: string;
  login_eyebrow: string;
  login_description: string;
  boundary_eyebrow: string;
  boundary_description: string;
  current_path_label: string;
  current_path_description: string;
}

export interface BundleUiCopy {
  home: BundleHomeCopy;
  admin: BundleAdminCopy;
}

export interface Campaign {
  id: string;
  title: string;
  source: 'blank' | 'seed';
  state: CampaignState;
  min_n: number;
  max_n: number;
  outline_status: 'collecting_brief' | 'ready_for_review';
  outline: OutlineArtifact;
  agent_models?: AgentModelSelections | null;
  created_at: string;
  updated_at: string;
}

export interface DesignerTurn {
  id: string;
  role: 'designer' | 'scientist';
  content: string;
  created_at: string;
}

export interface DesignerSession {
  id: string;
  campaign_id: string;
  status: 'idle' | 'active' | 'ready_for_review';
  turns: DesignerTurn[];
  updated_at: string;
}

export interface CampaignBundleResponse {
  campaign: Campaign;
  designer_session: DesignerSession | null;
  metrics: CampaignMetrics;
  readiness: OutlineReadiness;
  next_states: CampaignState[];
  outline_revisions: OutlineRevision[];
  invites?: Invite[];
  sessions?: InterviewSessionRecord[];
}

export interface CampaignSeedSummary {
  slug: string;
  title: string;
  description: string;
  min_n: number;
  max_n: number;
}

export interface ProductBundleManifest {
  slug: string;
  name: string;
  runtime: string;
  public_base_url: string;
  branding: BundleBranding;
  ui: BundleUiCopy;
  campaigns: Array<{ slug: string; seed: string }>;
}

export interface BundleCatalogResponse {
  bundle: ProductBundleManifest;
  seeds: CampaignSeedSummary[];
}

export interface OutlineReadinessCheck {
  key: string;
  label: string;
  ready: boolean;
  detail: string;
}

export interface OutlineReadiness {
  ready_for_review: boolean;
  completed: number;
  total: number;
  checks: OutlineReadinessCheck[];
}

export interface CampaignMetrics {
  invite_count: number;
  active_invite_count: number;
  used_invite_count: number;
  revoked_invite_count: number;
  session_count: number;
  active_session_count: number;
  finished_session_count: number;
}

export interface OutlineRevision {
  id: string;
  campaign_id: string;
  source: 'blank' | 'seed' | 'designer';
  summary: string;
  changed_sections: string[];
  outline: OutlineArtifact;
  created_at: string;
}

export interface CampaignOverviewItem {
  campaign: Campaign;
  designer_session: DesignerSession | null;
  metrics: CampaignMetrics;
  readiness: OutlineReadiness;
  next_states: CampaignState[];
  latest_outline_revision: OutlineRevision | null;
}

export interface CampaignOverviewSummary {
  total_campaigns: number;
  seeded_campaign_count: number;
  review_ready_count: number;
  live_campaign_count: number;
  active_session_count: number;
}

export interface CampaignOverviewResponse {
  bundle: ProductBundleManifest;
  seeds: CampaignSeedSummary[];
  summary: CampaignOverviewSummary;
  items: CampaignOverviewItem[];
}

export interface AdminSessionResponse {
  authenticated: boolean;
  expires_at: string | null;
}

export interface Invite {
  id: string;
  campaign_id: string;
  token: string;
  label: string;
  status: 'active' | 'used' | 'revoked';
  created_at: string;
  used_at: string | null;
  session_id: string | null;
}

export interface InviteInfoResponse {
  invite_id: string;
  campaign_id: string;
  campaign_title: string;
  consent_language: string;
  micro_form_schema: MicroFormField[];
  status: 'active' | 'used' | 'revoked';
}

export interface ValidationSnapshot {
  coverage_score?: number;
  quality_score?: number;
  follow_up_needed?: boolean;
  follow_up_reason?: string;
  is_spam?: boolean;
  extracted_concepts?: Array<{ label: string; type?: string }>;
  extracted_relations?: Array<Record<string, unknown>>;
  objective_tags?: string[];
  closing?: boolean;
  close_reason?: string;
  control_signal?: ParticipantControl;
}

export interface InterviewTurnRecord {
  id: string;
  session_id: string;
  role: 'agent' | 'participant';
  content: string;
  index: number;
  validation: ValidationSnapshot | null;
  brain_b_intent: BrainIntentRecord | null;
  get_user_input: GetUserInputPayload | null;
  created_at: string;
}

export interface InterviewSessionRecord {
  id: string;
  campaign_id: string;
  invite_id: string | null;
  participant_token: string;
  consent_mode: 'anonymous' | 'named';
  identity_label: string;
  persona_snapshot: Record<string, string>;
  pinned_endpoint: string;
  status: 'active' | 'paused' | 'finished' | 'abandoned';
  started_at: string;
  updated_at: string;
  finished_at: string | null;
  close_reason: string | null;
  paused_reason: string | null;
  abandoned_reason: string | null;
  turns: InterviewTurnRecord[];
}

export interface SessionBundleResponse {
  session: InterviewSessionRecord;
  campaign: Campaign;
}

export interface RedeemInviteResponse {
  session: InterviewSessionRecord;
  campaign_title: string;
}

export interface RuntimeContextResponse {
  app_name: string;
  runtime_name: string;
  bundle_dir: string;
  bundle_slug: string;
  bundle_name: string;
  public_base_url: string;
  declared_public_base_url: string | null;
  branding: BundleBranding;
  ui: BundleUiCopy;
  campaign_seed_count: number;
}

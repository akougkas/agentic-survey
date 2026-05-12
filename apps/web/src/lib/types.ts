export type CampaignState =
  | 'draft'
  | 'designing'
  | 'reviewing'
  | 'live'
  | 'monitoring'
  | 'closing'
  | 'archived';

export type AgentRole = 'chatter' | 'scientist' | 'validator' | 'analyst' | 'embedding' | 'ingest';
export type Endpoint = 'chatter' | 'scientist';
export type ReasoningMode = 'off' | 'on' | 'budget';
export type ReasoningKwarg = 'enable_thinking' | 'reasoning_effort' | 'none';
export type AgentModelSelections = Partial<Record<AgentRole, string>>;
export type ParticipantControl = 'pause' | 'skip' | 'continue' | 'stop';

export interface CatalogEntry {
  catalog_id: string;
  role: AgentRole;
  endpoint: Endpoint;
  model_id: string;
  label: string;
  notes?: string | null;
  enabled: boolean;
  is_default: boolean;
  reasoning_mode: ReasoningMode;
  reasoning_budget_tokens?: number | null;
  reasoning_kwarg: ReasoningKwarg;
  temperature?: number | null;
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
  reasoning_mode: ReasoningMode;
  reasoning_budget_tokens?: number | null;
  reasoning_kwarg: ReasoningKwarg;
  temperature?: number | null;
}

export interface OutlineRubric {
  coverage_dimensions: string[];
  risk_checks: string[];
  mandatory_close_axes: string[];
}

export interface MicroFormField {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
  options?: string[];
}

export interface ParticipantFAQEntry {
  key: string;
  question: string;
  answer: string;
  tags: string[];
}

export interface RiskEntry {
  risk: string;
  mitigation: string;
}

export interface DecisionGate {
  gate: string;
  rationale: string;
}

export interface SurveyQuestion {
  id: string;
  tier: string;
  prompt: string;
  kind: 'open' | 'select_one' | 'select_many' | 'likert_5' | 'rank';
  options: string[];
  applies_to_roles: string[];
  axis_tag: string;
  notes: string;
  follow_up_hints: string[];
  saturation_signals: string[];
  leading_language_avoid: string[];
}

export interface OutlineArtifact {
  research_question: string;
  sampling_frame: string;
  exclusion_criteria: string;
  publication_intent: string;
  axes: string[];
  objectives: string[];
  probes: string[];
  question_bank: SurveyQuestion[];
  risk_register: RiskEntry[];
  grounding_sources_approved: string[];
  readiness_rationale: string;
  decision_gate: DecisionGate | null;
  suggested_search_queries: string[];
  min_n: number;
  max_n: number;
  rubric: OutlineRubric;
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

export interface AxisCoverage {
  axis: string;
  score: number;
  gap: string;
}

export type QuestionCoverageStatus = 'pending' | 'targeting' | 'partial' | 'satisfied' | 'skipped';

export interface QuestionCoverage {
  question_id: string;
  status: QuestionCoverageStatus;
  confidence: number;
  evidence_quote: string;
  turn_id: string;
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

export interface BrainBIntent {
  active_axis: string;
  axes_coverage: AxisCoverage[];
  question_coverage: QuestionCoverage[];
  question_intent: string;
  get_user_input: GetUserInputOptions;
  outline_patch: OutlinePatch | null;
  ready_for_review: boolean;
  should_close: boolean;
  closing: boolean;
  retrieval_used: boolean;
  retrieval_chunks: string[];
  retrieval_audit_ids: string[];
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
  surfaces?: string[] | null;
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

export interface BundleInviteCopy {
  header_eyebrow: string;
  header_wordmark: string;
  header_subline: string;
  page_title: string;
  consent_title: string;
  anonymous_title: string;
  anonymous_description: string;
  named_title: string;
  named_description: string;
  micro_form_eyebrow: string;
  micro_form_description: string;
  micro_form_required_hint: string;
  micro_form_answer_note: string;
  start_button_idle: string;
  start_button_pending: string;
  next_eyebrow: string;
  next_steps: string[];
  closed_title: string;
  closed_status_eyebrow: string;
  closed_status_template: string;
  closed_used_message: string;
  closed_revoked_message: string;
  closed_fresh_link_message: string;
}

export interface BundleChatCopy {
  header_eyebrow: string;
  header_wordmark: string;
  header_subline: string;
  page_title: string;
  conversation_heading: string;
  transcript_locked_label: string;
  agent_composing_label: string;
  working_notes_eyebrow: string;
  working_notes_heading: string;
  retrieved_heading: string;
  retrieved_description_singular: string;
  retrieved_description_plural: string;
  concepts_heading: string;
  concepts_empty: string;
  turn_counter_template: string;
  active_footer: string;
  paused_footer: string;
  finished_footer: string;
  session_complete_eyebrow: string;
  return_home_label: string;
  empty_state: string;
  placeholder_default: string;
  placeholder_with_chips: string;
  submit_idle: string;
  submit_pending: string;
  submit_finished: string;
  thinking_messages: string[];
}

export interface BundleFooterCopy {
  hosted_by: string;
  developed_by: string;
  copyright: string;
}

export interface BundleUiCopy {
  home: BundleHomeCopy;
  admin: BundleAdminCopy;
  invite: BundleInviteCopy;
  chat: BundleChatCopy;
  footer: BundleFooterCopy;
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

export interface CampaignSeedSummary {
  slug: string;
  title: string;
  description: string;
  min_n: number;
  max_n: number;
}

export interface BundleCatalogResponse {
  bundle: ProductBundleManifest;
  seeds: CampaignSeedSummary[];
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
  brain_b_intent: BrainBIntent | null;
  get_user_input: GetUserInputOptions | null;
  created_at: string;
}

export interface DesignerSession {
  id: string;
  campaign_id: string;
  status: 'idle' | 'active' | 'ready_for_review';
  turns: DesignerTurn[];
  updated_at: string;
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
  brain_b_intent: BrainBIntent | null;
  get_user_input: GetUserInputOptions | null;
  retrieval_audit_id: string | null;
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
  micro_form_answers?: Record<string, string>;
  turns: InterviewTurnRecord[];
  next_plan: BrainBIntent | null;
}

export interface MethodObservation {
  id: string;
  session_id: string;
  campaign_id: string;
  author: string;
  body: string;
  tags: string[];
  created_at: string;
}

export interface MethodObservationCreate {
  body: string;
  tags?: string[] | null;
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

export interface InviteInfoResponse {
  invite_id: string;
  campaign_id: string;
  campaign_title: string;
  consent_language: string;
  micro_form_schema: MicroFormField[];
  status: 'active' | 'used' | 'revoked';
}

export interface SessionBundleResponse {
  session: InterviewSessionRecord;
  campaign: Campaign;
}

export interface QuestionAnswerRow {
  session_id: string;
  identity_label: string;
  consent_mode: string;
  started_at: string;
  finished_at: string;
  role_self_description: string;
  evidence_of_belonging: string;
  question_id: string;
  tier: string;
  axis_tag: string;
  applies_to_roles: string;
  status: QuestionCoverageStatus;
  confidence: number;
  evidence_quote: string;
  turn_id: string;
  prompt: string;
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
  admin_surfaces_allowlist?: string[] | null;
  campaign_seed_count: number;
}

// M8 -----------------------------------------------------------------

export type KnowledgeSourceKind =
  | 'url'
  | 'pdf'
  | 'raw_text'
  | 'searxng_suggestion'
  | 'bundle_seed';

export type KnowledgeSourceStatus =
  | 'queued'
  | 'fetching'
  | 'extracting'
  | 'chunking'
  | 'embedding'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'failed'
  | 'retired';

export interface KnowledgeSource {
  id: string;
  campaign_id: string;
  kind: KnowledgeSourceKind;
  title: string;
  url: string | null;
  hash: string;
  status: KnowledgeSourceStatus;
  rationale: string;
  approved_at: string | null;
  approved_by: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSourceSummary {
  source: KnowledgeSource;
  chunk_count: number;
}

export interface KnowledgeSourceTimeline {
  campaign_id: string;
  by_status: Partial<Record<KnowledgeSourceStatus, KnowledgeSourceSummary[]>>;
  total: number;
}

export interface WebSearchResult {
  title: string;
  url: string;
  snippet: string;
  source: string;
}

export interface KnowledgeSearchResponse {
  campaign_id: string;
  query: string;
  results: WebSearchResult[];
  created_source_ids: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  first_seen: string;
  mention_count: number;
}

export interface GraphEdge {
  from_id: string;
  to_id: string;
  edge_table: 'mentioned_with' | 'contradicts';
  kind: string;
  confidence: number;
  session_id: string;
  turn_id: string;
  created_at: string;
}

export interface GraphSnapshotResponse {
  campaign_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  latest_event_seq: number;
}

export interface GraphDeltaNode {
  id: string;
  label: string;
  type: string;
  is_new: boolean;
}

export interface GraphDeltaEdge {
  from: string;
  to: string;
  kind: string;
  edge_table: 'mentioned_with' | 'contradicts';
  confidence: number;
}

export interface GraphDelta {
  add_nodes: GraphDeltaNode[];
  add_edges: GraphDeltaEdge[];
  light_up: string[];
}

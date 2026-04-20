from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from secrets import token_urlsafe
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from agentic_survey.engine.state_machine import CampaignState, transition_or_raise
from agentic_survey.llm.catalog import AGENT_ROLES, AgentRole as CatalogRole, CatalogEntry, seed_entries

ParticipantControl = Literal["pause", "skip", "continue", "stop"]
SharedContextKind = Literal[
    "study_context",
    "market_context",
    "technical_context",
    "aggregate_graph_context",
]


class MicroFormField(BaseModel):
    key: str
    label: str
    field_type: str = "text"
    required: bool = True


class ParticipantFAQEntry(BaseModel):
    key: str
    question: str
    answer: str
    tags: list[str] = Field(default_factory=list)


class GetUserInputPayload(BaseModel):
    question: str = ""
    options: list[str] = Field(default_factory=list)
    allow_free_text: bool = True
    participant_controls: list[ParticipantControl] = Field(default_factory=list)
    suggested_control: ParticipantControl | None = None
    sensitive_turn: bool = False


class BrainIntentRecord(BaseModel):
    response_mode: Literal["probe", "faq", "advice_refusal", "closing"] = "probe"
    question_intent: str = ""
    faq_key: str | None = None
    shared_context_used: list[SharedContextKind] = Field(default_factory=list)
    should_close: bool = False
    close_reason: str = ""
    get_user_input: GetUserInputPayload | None = None


class OutlineRubric(BaseModel):
    coverage_dimensions: list[str] = Field(default_factory=list)
    risk_checks: list[str] = Field(default_factory=list)


class OutlineArtifact(BaseModel):
    objectives: list[str] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)
    rubric: OutlineRubric
    min_n: int
    max_n: int
    freshness_query: str
    persona_hints: dict[str, str]
    consent_language: str
    micro_form_schema: list[MicroFormField]
    scientist_summary: str = ""
    study_context: str = ""
    market_context: str = ""
    technical_context: str = ""
    aggregate_graph_context: str = ""
    participant_faq: list[ParticipantFAQEntry] = Field(default_factory=list)


class DesignerTurn(BaseModel):
    id: str
    role: Literal["designer", "scientist"]
    content: str
    brain_b_intent: BrainIntentRecord | None = None
    get_user_input: GetUserInputPayload | None = None
    created_at: str


class DesignerSession(BaseModel):
    id: str
    campaign_id: str
    status: Literal["idle", "active", "ready_for_review"] = "idle"
    turns: list[DesignerTurn] = Field(default_factory=list)
    updated_at: str


class Campaign(BaseModel):
    id: str
    title: str
    source: Literal["blank", "seed"] = "blank"
    state: CampaignState
    min_n: int
    max_n: int
    outline_status: Literal["collecting_brief", "ready_for_review"] = "collecting_brief"
    outline: OutlineArtifact
    agent_models: dict[str, str] | None = None
    created_at: str
    updated_at: str


class OutlineRevision(BaseModel):
    id: str
    campaign_id: str
    source: Literal["blank", "seed", "designer"]
    summary: str
    changed_sections: list[str] = Field(default_factory=list)
    outline: OutlineArtifact
    created_at: str


KnowledgeSourceKind = Literal["url", "pdf", "raw_text", "searxng_suggestion", "bundle_seed"]
KnowledgeSourceStatus = Literal[
    "queued",
    "fetching",
    "extracting",
    "chunking",
    "embedding",
    "pending_approval",
    "approved",
    "rejected",
    "failed",
    "retired",
]


class KnowledgeSource(BaseModel):
    id: str
    campaign_id: str
    kind: KnowledgeSourceKind
    title: str
    url: str | None = None
    hash: str
    status: KnowledgeSourceStatus
    rationale: str = ""
    approved_at: str | None = None
    approved_by: str | None = None
    error_detail: str | None = None
    created_at: str
    updated_at: str


class KnowledgeChunk(BaseModel):
    id: str
    campaign_id: str
    source_id: str
    content: str
    position: int
    char_start: int
    char_end: int
    approved: bool = False
    created_at: str


class RetrievalAuditRow(BaseModel):
    id: str
    campaign_id: str
    surface: Literal["designer", "interviewer"]
    query: str
    top_k: int
    chunk_ids: list[str] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    created_at: str


class ChunkHit(BaseModel):
    chunk_id: str
    content: str
    source_id: str
    source_title: str
    score: float
    start_char: int
    end_char: int


class AdminSession(BaseModel):
    token: str
    created_at: datetime
    expires_at: datetime


class Invite(BaseModel):
    id: str
    campaign_id: str
    token: str
    label: str = ""
    status: Literal["active", "used", "revoked"] = "active"
    created_at: str
    used_at: str | None = None
    session_id: str | None = None


class InterviewTurnRecord(BaseModel):
    id: str
    session_id: str
    role: Literal["agent", "participant"]
    content: str
    index: int
    validation: dict | None = None
    brain_b_intent: BrainIntentRecord | None = None
    brain_b_intent_v2: dict | None = None
    get_user_input: GetUserInputPayload | None = None
    retrieval_audit_id: str | None = None
    created_at: str


class InterviewSessionRecord(BaseModel):
    id: str
    campaign_id: str
    invite_id: str | None
    participant_token: str
    consent_mode: Literal["anonymous", "named"]
    identity_label: str = ""
    persona_snapshot: dict
    pinned_endpoint: str
    status: Literal["active", "paused", "finished", "abandoned"] = "active"
    started_at: str
    updated_at: str
    finished_at: str | None = None
    close_reason: str | None = None
    paused_reason: str | None = None
    abandoned_reason: str | None = None
    turns: list[InterviewTurnRecord] = Field(default_factory=list)


DEFAULT_PERSONA_HINTS = {
    "name": "Mira",
    "role": "synthetic field researcher",
    "tone": "measured, lucid, slightly warm",
    "behavior": (
        "Ask one precise question at a time, summarize signal before probing,"
        " and state uncertainty plainly."
    ),
}

DEFAULT_MICRO_FORM_SCHEMA = [
    MicroFormField(key="discipline", label="Primary discipline"),
    MicroFormField(key="role", label="Research role"),
    MicroFormField(key="career_stage", label="Career stage"),
]

DEFAULT_RUBRIC = OutlineRubric(
    coverage_dimensions=[
        "Concrete moment, workflow stage, or decision point where the topic appears",
        "Observed upside, friction, uncertainty, or risk",
        "Validation, evidence, or decision criteria used by the participant",
    ],
    risk_checks=[
        "Avoid leading prompts and premature conclusions",
        "Ask for specific examples before drawing themes",
        "Separate reported behavior from interpretation and recommendation",
    ],
)

DEFAULT_AGGREGATE_GRAPH_CONTEXT = (
    "If shared study signal is shown during the interview, it stays aggregate and non-identifying."
)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _timestamp() -> str:
    return _utcnow().isoformat()


def _campaign_id() -> str:
    return f"campaign-{uuid4().hex[:12]}"


def _designer_session_id() -> str:
    return f"designer-{uuid4().hex[:12]}"


def _invite_id() -> str:
    return f"invite-{uuid4().hex[:12]}"


def _interview_session_id() -> str:
    return f"session-{uuid4().hex[:12]}"


def _turn_id() -> str:
    return f"turn-{uuid4().hex[:12]}"


def _outline_revision_id() -> str:
    return f"outline-{uuid4().hex[:12]}"


def _default_study_context(title: str, summary: str) -> str:
    if summary.strip():
        return summary.strip()
    return (
        f"This study is about {title}. Mira is here to understand how it shows up in real work, "
        "using concrete examples rather than polished summaries."
    )


def _default_participant_faq(
    *,
    title: str,
    summary: str,
    consent_language: str,
) -> list[ParticipantFAQEntry]:
    return [
        ParticipantFAQEntry(
            key="study-purpose",
            question="What is this study about?",
            answer=_default_study_context(title, summary),
            tags=["study", "purpose", "about", "why"],
        ),
        ParticipantFAQEntry(
            key="scientist",
            question="Who is running this study?",
            answer=(
                "I can share the approved study description, but I do not have a separate scientist bio or "
                "backstory approved for participants in this session."
            ),
            tags=["scientist", "researcher", "who", "running"],
        ),
        ParticipantFAQEntry(
            key="sponsor",
            question="Who is sponsoring this study?",
            answer=(
                "I do not have sponsor details beyond the approved study description for this session."
            ),
            tags=["sponsor", "funding", "backed", "company"],
        ),
        ParticipantFAQEntry(
            key="logistics",
            question="What happens with my answers?",
            answer=(
                f"{consent_language.strip()} You can skip, pause, continue later, or stop at any point."
            ),
            tags=["logistics", "consent", "quoted", "answers", "anonymous", "named"],
        ),
    ]


def _catalog_key(catalog_id: str, role: CatalogRole) -> tuple[str, CatalogRole]:
    return (catalog_id, role)


class InMemoryRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._campaigns: dict[str, Campaign] = {}
        self._catalog: dict[tuple[str, CatalogRole], CatalogEntry] = {}
        self._outline_revisions_by_campaign: dict[str, list[OutlineRevision]] = {}
        self._designer_sessions: dict[str, DesignerSession] = {}
        self._admin_sessions: dict[str, AdminSession] = {}
        self._invites_by_id: dict[str, Invite] = {}
        self._invites_by_token: dict[str, str] = {}
        self._invites_by_campaign: dict[str, list[str]] = {}
        self._interview_sessions: dict[str, InterviewSessionRecord] = {}
        self._interview_sessions_by_participant: dict[str, str] = {}
        self._interview_sessions_by_campaign: dict[str, list[str]] = {}
        self._knowledge_sources: dict[str, KnowledgeSource] = {}
        self._knowledge_sources_by_campaign: dict[str, list[str]] = {}
        self._knowledge_chunks: dict[str, KnowledgeChunk] = {}
        self._knowledge_chunks_by_source: dict[str, list[str]] = {}
        self._retrieval_audits: dict[str, RetrievalAuditRow] = {}
        self._retrieval_audits_by_campaign: dict[str, list[str]] = {}
        self._seed_catalog_locked()

    def create_admin_session(self, ttl_hours: int) -> AdminSession:
        now = _utcnow()
        session = AdminSession(
            token=token_urlsafe(32),
            created_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
        )
        with self._lock:
            self._admin_sessions[session.token] = session
        return session.model_copy(deep=True)

    def get_admin_session(self, token: str) -> AdminSession | None:
        with self._lock:
            session = self._admin_sessions.get(token)
            if session is None:
                return None
            if session.expires_at <= _utcnow():
                self._admin_sessions.pop(token, None)
                return None
        return session.model_copy(deep=True)

    def revoke_admin_session(self, token: str) -> None:
        with self._lock:
            self._admin_sessions.pop(token, None)

    def list_campaigns(self) -> list[Campaign]:
        with self._lock:
            campaigns = sorted(
                self._campaigns.values(),
                key=lambda campaign: campaign.updated_at,
                reverse=True,
            )
        return [campaign.model_copy(deep=True) for campaign in campaigns]

    def list_catalog(self, role: CatalogRole | None = None) -> list[CatalogEntry]:
        with self._lock:
            entries = list(self._catalog.values())
        if role is not None:
            entries = [entry for entry in entries if entry.role == role]
        entries.sort(key=lambda entry: (AGENT_ROLES.index(entry.role), entry.catalog_id, entry.label))
        return [entry.model_copy(deep=True) for entry in entries]

    def get_catalog_entry(self, catalog_id: str, role: CatalogRole) -> CatalogEntry | None:
        with self._lock:
            entry = self._catalog.get(_catalog_key(catalog_id, role))
        return None if entry is None else entry.model_copy(deep=True)

    def create_catalog_entry(self, entry: CatalogEntry) -> CatalogEntry:
        with self._lock:
            key = _catalog_key(entry.catalog_id, entry.role)
            if key in self._catalog:
                raise ValueError(f"Catalog entry already exists for {entry.catalog_id}/{entry.role}")
            stored = entry.model_copy(deep=True)
            if not stored.enabled:
                stored.is_default = False
            stored.created_at = _timestamp()
            stored.updated_at = stored.created_at
            self._catalog[key] = stored
            if stored.is_default:
                self._set_default_locked(stored.catalog_id, stored.role)
        return stored.model_copy(deep=True)

    def update_catalog_entry(
        self,
        catalog_id: str,
        role: CatalogRole,
        patch: dict,
    ) -> CatalogEntry:
        allowed_fields = {"endpoint", "model_id", "label", "notes", "enabled", "is_default"}
        unknown = set(patch) - allowed_fields
        if unknown:
            raise ValueError(f"Unsupported catalog patch fields: {', '.join(sorted(unknown))}")
        with self._lock:
            key = _catalog_key(catalog_id, role)
            entry = self._catalog.get(key)
            if entry is None:
                raise KeyError(f"Catalog entry not found for {catalog_id}/{role}")
            for field_name, value in patch.items():
                setattr(entry, field_name, value)
            if not entry.enabled:
                entry.is_default = False
            entry.updated_at = _timestamp()
            if entry.is_default:
                self._set_default_locked(entry.catalog_id, entry.role)
            elif patch.get("is_default") is False:
                self._unset_default_locked(entry.catalog_id, entry.role)
        return entry.model_copy(deep=True)

    def delete_catalog_entry(self, catalog_id: str, role: CatalogRole) -> None:
        with self._lock:
            key = _catalog_key(catalog_id, role)
            if key not in self._catalog:
                raise KeyError(f"Catalog entry not found for {catalog_id}/{role}")
            self._catalog.pop(key)

    def set_campaign_models(
        self,
        campaign_id: str,
        models: dict[str, str] | None,
    ) -> Campaign:
        normalized = self._normalize_agent_models(models)
        with self._lock:
            campaign = self._campaigns[campaign_id]
            campaign.agent_models = normalized
            campaign.updated_at = _timestamp()
        return campaign.model_copy(deep=True)

    def update_campaign_models(
        self,
        campaign_id: str,
        patch: dict[str, str | None],
    ) -> Campaign:
        with self._lock:
            campaign = self._campaigns[campaign_id]
            current = dict(campaign.agent_models or {})
            for role, catalog_id in patch.items():
                self._validate_agent_role(role)
                if catalog_id is None:
                    current.pop(role, None)
                    continue
                self._require_catalog_selection_locked(role, catalog_id)
                current[role] = catalog_id
            campaign.agent_models = current or None
            campaign.updated_at = _timestamp()
        return campaign.model_copy(deep=True)

    def create_campaign(
        self,
        title: str,
        min_n: int,
        max_n: int,
        *,
        agent_models: dict[str, str] | None = None,
        outline: OutlineArtifact | None = None,
        source: Literal["blank", "seed"] = "blank",
        state: CampaignState = CampaignState.DRAFT,
        outline_status: Literal["collecting_brief", "ready_for_review"] = "collecting_brief",
    ) -> Campaign:
        now = _timestamp()
        normalized_agent_models = self._normalize_agent_models(agent_models)
        initial_outline = outline.model_copy(deep=True) if outline is not None else self._build_outline(
            title=title,
            min_n=min_n,
            max_n=max_n,
        )
        campaign = Campaign(
            id=_campaign_id(),
            title=title,
            source=source,
            state=state,
            min_n=min_n,
            max_n=max_n,
            outline=initial_outline,
            outline_status=outline_status,
            agent_models=normalized_agent_models,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._campaigns[campaign.id] = campaign
            self._outline_revisions_by_campaign[campaign.id] = [
                OutlineRevision(
                    id=_outline_revision_id(),
                    campaign_id=campaign.id,
                    source="seed" if source == "seed" else "blank",
                    summary=(
                        "Campaign created from the mounted bundle seed."
                        if source == "seed"
                        else "Blank draft created with the default outline."
                    ),
                    changed_sections=["initial_outline"],
                    outline=initial_outline.model_copy(deep=True),
                    created_at=now,
                )
            ]
        return campaign.model_copy(deep=True)

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        with self._lock:
            campaign = self._campaigns.get(campaign_id)
        return None if campaign is None else campaign.model_copy(deep=True)

    def get_designer_session(self, campaign_id: str) -> DesignerSession | None:
        with self._lock:
            session = self._designer_sessions.get(campaign_id)
        return None if session is None else session.model_copy(deep=True)

    def list_outline_revisions(self, campaign_id: str) -> list[OutlineRevision]:
        with self._lock:
            revisions = list(self._outline_revisions_by_campaign.get(campaign_id, []))
        return [revision.model_copy(deep=True) for revision in revisions]

    def start_designer_session(self, campaign_id: str, opening_message: str) -> DesignerSession:
        with self._lock:
            campaign = self._campaigns[campaign_id]
            session = self._designer_sessions.get(campaign_id)
            if session is None:
                session = DesignerSession(
                    id=_designer_session_id(),
                    campaign_id=campaign_id,
                    status="active",
                    updated_at=_timestamp(),
                )
                self._designer_sessions[campaign_id] = session
            if campaign.state == CampaignState.DRAFT:
                campaign.state = transition_or_raise(campaign.state, CampaignState.DESIGNING)
            campaign.updated_at = _timestamp()
            if not session.turns:
                session.turns.append(
                    DesignerTurn(
                        id=f"turn-{uuid4().hex[:12]}",
                        role="designer",
                        content=opening_message,
                        created_at=_timestamp(),
                    )
                )
            session.status = "active"
            session.updated_at = _timestamp()
            return session.model_copy(deep=True)

    def append_designer_turn(
        self,
        campaign_id: str,
        role: Literal["designer", "scientist"],
        content: str,
        *,
        brain_b_intent: BrainIntentRecord | None = None,
        get_user_input: GetUserInputPayload | None = None,
    ) -> DesignerTurn:
        turn = DesignerTurn(
            id=f"turn-{uuid4().hex[:12]}",
            role=role,
            content=content,
            brain_b_intent=brain_b_intent.model_copy(deep=True) if brain_b_intent is not None else None,
            get_user_input=get_user_input.model_copy(deep=True) if get_user_input is not None else None,
            created_at=_timestamp(),
        )
        with self._lock:
            session = self._designer_sessions[campaign_id]
            session.turns.append(turn)
            session.updated_at = _timestamp()
            campaign = self._campaigns[campaign_id]
            campaign.updated_at = session.updated_at
        return turn.model_copy(deep=True)

    def update_outline(
        self,
        campaign_id: str,
        outline: OutlineArtifact,
        *,
        ready_for_review: bool,
    ) -> Campaign:
        with self._lock:
            campaign = self._campaigns[campaign_id]
            previous_outline = campaign.outline.model_copy(deep=True)
            previous_status = campaign.outline_status
            campaign.outline = outline.model_copy(deep=True)
            campaign.outline_status = "ready_for_review" if ready_for_review else "collecting_brief"
            campaign.updated_at = _timestamp()
            session = self._designer_sessions.get(campaign_id)
            if session is not None:
                session.status = "ready_for_review" if ready_for_review else "active"
                session.updated_at = campaign.updated_at
            changed_sections = self._changed_outline_sections(previous_outline, outline)
            if previous_status != campaign.outline_status:
                changed_sections.append("review_status")
            if changed_sections:
                self._append_outline_revision_locked(
                    campaign_id,
                    source="designer",
                    outline=campaign.outline,
                    changed_sections=changed_sections,
                    summary=self._build_outline_revision_summary(
                        changed_sections,
                        ready_for_review=ready_for_review,
                    ),
                    created_at=campaign.updated_at,
                )
        return campaign.model_copy(deep=True)

    def advance_campaign(self, campaign_id: str, target: CampaignState) -> Campaign:
        with self._lock:
            campaign = self._campaigns[campaign_id]
            campaign.state = transition_or_raise(campaign.state, target)
            campaign.updated_at = _timestamp()
        return campaign.model_copy(deep=True)

    def create_invite(self, campaign_id: str, label: str = "") -> Invite:
        invite = Invite(
            id=_invite_id(),
            campaign_id=campaign_id,
            token=token_urlsafe(18),
            label=label,
            created_at=_timestamp(),
        )
        with self._lock:
            self._invites_by_id[invite.id] = invite
            self._invites_by_token[invite.token] = invite.id
            self._invites_by_campaign.setdefault(campaign_id, []).append(invite.id)
        return invite.model_copy(deep=True)

    def list_invites(self, campaign_id: str) -> list[Invite]:
        with self._lock:
            ids = list(self._invites_by_campaign.get(campaign_id, []))
            return [self._invites_by_id[invite_id].model_copy(deep=True) for invite_id in ids]

    def get_invite(self, invite_id: str) -> Invite | None:
        with self._lock:
            invite = self._invites_by_id.get(invite_id)
        return None if invite is None else invite.model_copy(deep=True)

    def get_invite_by_token(self, token: str) -> Invite | None:
        with self._lock:
            invite_id = self._invites_by_token.get(token)
            if invite_id is None:
                return None
            return self._invites_by_id[invite_id].model_copy(deep=True)

    def mark_invite_used(self, invite_id: str, session_id: str) -> None:
        with self._lock:
            invite = self._invites_by_id.get(invite_id)
            if invite is None:
                return
            invite.status = "used"
            invite.used_at = _timestamp()
            invite.session_id = session_id

    def revoke_invite(self, invite_id: str) -> Invite | None:
        with self._lock:
            invite = self._invites_by_id.get(invite_id)
            if invite is None:
                return None
            invite.status = "revoked"
            invite.used_at = None
            invite.session_id = None
        return invite.model_copy(deep=True)

    def start_interview_session(
        self,
        *,
        campaign_id: str,
        invite_id: str | None,
        consent_mode: Literal["anonymous", "named"],
        identity_label: str,
        persona_snapshot: dict,
        pinned_endpoint: str,
    ) -> InterviewSessionRecord:
        now = _timestamp()
        session = InterviewSessionRecord(
            id=_interview_session_id(),
            campaign_id=campaign_id,
            invite_id=invite_id,
            participant_token=token_urlsafe(32),
            consent_mode=consent_mode,
            identity_label=identity_label.strip()[:120],
            persona_snapshot=persona_snapshot,
            pinned_endpoint=pinned_endpoint,
            status="active",
            started_at=now,
            updated_at=now,
        )
        with self._lock:
            self._interview_sessions[session.id] = session
            self._interview_sessions_by_participant[session.participant_token] = session.id
            self._interview_sessions_by_campaign.setdefault(campaign_id, []).append(session.id)
        return session.model_copy(deep=True)

    def get_interview_session(self, session_id: str) -> InterviewSessionRecord | None:
        with self._lock:
            session = self._interview_sessions.get(session_id)
            return None if session is None else session.model_copy(deep=True)

    def get_interview_session_by_participant_token(self, token: str) -> InterviewSessionRecord | None:
        with self._lock:
            session_id = self._interview_sessions_by_participant.get(token)
            if session_id is None:
                return None
            return self._interview_sessions[session_id].model_copy(deep=True)

    def list_interview_sessions(self, campaign_id: str) -> list[InterviewSessionRecord]:
        with self._lock:
            ids = list(self._interview_sessions_by_campaign.get(campaign_id, []))
            return [self._interview_sessions[sid].model_copy(deep=True) for sid in ids]

    def append_interview_turn(
        self,
        session_id: str,
        *,
        role: Literal["agent", "participant"],
        content: str,
        validation: dict | None = None,
        brain_b_intent: BrainIntentRecord | None = None,
        brain_b_intent_v2: dict | None = None,
        get_user_input: GetUserInputPayload | None = None,
        retrieval_audit_id: str | None = None,
    ) -> InterviewTurnRecord:
        with self._lock:
            session = self._interview_sessions[session_id]
            turn = InterviewTurnRecord(
                id=_turn_id(),
                session_id=session_id,
                role=role,
                content=content,
                index=len(session.turns),
                validation=validation,
                brain_b_intent=brain_b_intent.model_copy(deep=True) if brain_b_intent is not None else None,
                brain_b_intent_v2=dict(brain_b_intent_v2) if brain_b_intent_v2 is not None else None,
                get_user_input=get_user_input.model_copy(deep=True) if get_user_input is not None else None,
                retrieval_audit_id=retrieval_audit_id,
                created_at=_timestamp(),
            )
            session.turns.append(turn)
            session.updated_at = turn.created_at
        return turn.model_copy(deep=True)

    def pause_interview_session(self, session_id: str, *, reason: str) -> InterviewSessionRecord:
        with self._lock:
            session = self._interview_sessions[session_id]
            session.status = "paused"
            session.paused_reason = reason
            session.updated_at = _timestamp()
        return session.model_copy(deep=True)

    def resume_interview_session(self, session_id: str) -> InterviewSessionRecord:
        with self._lock:
            session = self._interview_sessions[session_id]
            session.status = "active"
            session.paused_reason = None
            session.updated_at = _timestamp()
        return session.model_copy(deep=True)

    def finish_interview_session(self, session_id: str, *, close_reason: str | None = None) -> InterviewSessionRecord:
        with self._lock:
            session = self._interview_sessions[session_id]
            session.status = "finished"
            session.finished_at = _timestamp()
            session.updated_at = session.finished_at
            session.close_reason = close_reason
            session.paused_reason = None
        return session.model_copy(deep=True)

    def _build_outline(self, *, title: str, min_n: int, max_n: int) -> OutlineArtifact:
        base_query = " ".join(part for part in title.split() if part).strip().lower()
        consent_language = (
            "Participants choose anonymous or named participation at session start;"
            " named responses may be quoted in later study outputs."
        )
        scientist_summary = ""
        return OutlineArtifact(
            objectives=["Clarify the core research question, participant segment, and decisions this study should inform."],
            probes=[
                "Which moments, workflows, or decisions matter most to the study?",
                "Where does uncertainty, friction, or false confidence show up most often?",
            ],
            rubric=DEFAULT_RUBRIC.model_copy(deep=True),
            min_n=min_n,
            max_n=max_n,
            freshness_query=base_query or "qualitative research interview campaign",
            persona_hints=DEFAULT_PERSONA_HINTS.copy(),
            consent_language=consent_language,
            micro_form_schema=[field.model_copy(deep=True) for field in DEFAULT_MICRO_FORM_SCHEMA],
            scientist_summary=scientist_summary,
            study_context=_default_study_context(title, scientist_summary),
            aggregate_graph_context=DEFAULT_AGGREGATE_GRAPH_CONTEXT,
            participant_faq=_default_participant_faq(
                title=title,
                summary=scientist_summary,
                consent_language=consent_language,
            ),
        )

    def _seed_catalog_locked(self) -> None:
        for entry in seed_entries():
            self._catalog[_catalog_key(entry.catalog_id, entry.role)] = entry.model_copy(deep=True)
        for role in AGENT_ROLES:
            defaults = [entry for entry in self._catalog.values() if entry.role == role and entry.is_default]
            if len(defaults) <= 1:
                continue
            first = defaults[0]
            for entry in defaults[1:]:
                entry.is_default = False
                entry.updated_at = first.updated_at

    def _normalize_agent_models(self, models: dict[str, str] | None) -> dict[str, str] | None:
        if models is None:
            return None
        normalized: dict[str, str] = {}
        with self._lock:
            for role, catalog_id in models.items():
                self._validate_agent_role(role)
                self._require_catalog_selection_locked(role, catalog_id)
                normalized[role] = catalog_id
        return normalized or None

    def _require_catalog_selection_locked(self, role: str, catalog_id: str) -> CatalogEntry:
        entry = self._catalog.get(_catalog_key(catalog_id, role))  # type: ignore[arg-type]
        if entry is None:
            raise ValueError(f"Unknown catalog entry for role {role}: {catalog_id}")
        if not entry.enabled:
            raise ValueError(f"Catalog entry is disabled for role {role}: {catalog_id}")
        return entry

    def _set_default_locked(self, catalog_id: str, role: CatalogRole) -> None:
        timestamp = _timestamp()
        for entry in self._catalog.values():
            if entry.role != role:
                continue
            should_be_default = entry.catalog_id == catalog_id and entry.enabled
            if entry.is_default != should_be_default:
                entry.is_default = should_be_default
                entry.updated_at = timestamp

    def _unset_default_locked(self, catalog_id: str, role: CatalogRole) -> None:
        entry = self._catalog.get(_catalog_key(catalog_id, role))
        if entry is None:
            return
        entry.is_default = False
        entry.updated_at = _timestamp()

    @staticmethod
    def _validate_agent_role(role: str) -> None:
        if role not in AGENT_ROLES:
            allowed = ", ".join(AGENT_ROLES)
            raise ValueError(f"Unsupported agent role '{role}'. Expected one of: {allowed}")

    def _append_outline_revision_locked(
        self,
        campaign_id: str,
        *,
        source: Literal["blank", "seed", "designer"],
        outline: OutlineArtifact,
        changed_sections: list[str],
        summary: str,
        created_at: str,
    ) -> None:
        revisions = self._outline_revisions_by_campaign.setdefault(campaign_id, [])
        revisions.append(
            OutlineRevision(
                id=_outline_revision_id(),
                campaign_id=campaign_id,
                source=source,
                summary=summary,
                changed_sections=list(changed_sections),
                outline=outline.model_copy(deep=True),
                created_at=created_at,
            )
        )

    @staticmethod
    def _changed_outline_sections(previous: OutlineArtifact, current: OutlineArtifact) -> list[str]:
        changed_sections: list[str] = []
        fields_to_track = [
            "scientist_summary",
            "objectives",
            "probes",
            "freshness_query",
            "consent_language",
            "persona_hints",
            "micro_form_schema",
            "rubric",
            "study_context",
            "market_context",
            "technical_context",
            "aggregate_graph_context",
            "participant_faq",
        ]
        for field_name in fields_to_track:
            if getattr(previous, field_name) != getattr(current, field_name):
                changed_sections.append(field_name)
        return changed_sections

    @staticmethod
    def _build_outline_revision_summary(
        changed_sections: list[str],
        *,
        ready_for_review: bool,
    ) -> str:
        labels = {
            "scientist_summary": "Brief summary",
            "objectives": "Objectives",
            "probes": "Interview probes",
            "freshness_query": "Freshness query",
            "consent_language": "Consent guidance",
            "persona_hints": "Interviewer persona",
            "micro_form_schema": "Participant fields",
            "rubric": "Rubric",
            "study_context": "Study context",
            "market_context": "Market context",
            "technical_context": "Technical context",
            "aggregate_graph_context": "Aggregate graph context",
            "participant_faq": "Participant FAQ",
            "review_status": "Readiness",
        }
        label_text = ", ".join(labels[section] for section in changed_sections[:3] if section in labels)
        if len(changed_sections) > 3:
            label_text = f"{label_text}, and more"
        if not label_text:
            label_text = "Outline"
        if ready_for_review:
            return f"{label_text} updated. Outline is ready for review."
        return f"{label_text} updated."


    def create_knowledge_source(
        self,
        *,
        campaign_id: str,
        kind: KnowledgeSourceKind,
        title: str,
        hash_value: str,
        url: str | None = None,
        rationale: str = "",
        status: KnowledgeSourceStatus = "pending_approval",
    ) -> KnowledgeSource:
        now = _timestamp()
        source = KnowledgeSource(
            id=f"ksrc-{uuid4().hex[:12]}",
            campaign_id=campaign_id,
            kind=kind,
            title=title,
            url=url,
            hash=hash_value,
            status=status,
            rationale=rationale,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._knowledge_sources[source.id] = source
            self._knowledge_sources_by_campaign.setdefault(campaign_id, []).append(source.id)
        return source.model_copy(deep=True)

    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None:
        with self._lock:
            source = self._knowledge_sources.get(source_id)
            return None if source is None else source.model_copy(deep=True)

    def list_knowledge_sources(self, campaign_id: str) -> list[KnowledgeSource]:
        with self._lock:
            ids = list(self._knowledge_sources_by_campaign.get(campaign_id, []))
            return [self._knowledge_sources[sid].model_copy(deep=True) for sid in ids]

    def update_knowledge_source_status(
        self,
        source_id: str,
        *,
        status: KnowledgeSourceStatus,
        approved_by: str | None = None,
    ) -> KnowledgeSource:
        with self._lock:
            source = self._knowledge_sources[source_id]
            source.status = status
            source.updated_at = _timestamp()
            if status == "approved":
                source.approved_at = source.updated_at
                source.approved_by = approved_by or "scientist"
                for chunk_id in self._knowledge_chunks_by_source.get(source_id, []):
                    chunk = self._knowledge_chunks.get(chunk_id)
                    if chunk is not None:
                        chunk.approved = True
            elif status == "rejected":
                source.approved_at = None
                source.approved_by = None
                for chunk_id in self._knowledge_chunks_by_source.get(source_id, []):
                    chunk = self._knowledge_chunks.get(chunk_id)
                    if chunk is not None:
                        chunk.approved = False
            return source.model_copy(deep=True)

    def create_knowledge_chunk(
        self,
        *,
        campaign_id: str,
        source_id: str,
        content: str,
        position: int,
        char_start: int,
        char_end: int,
        approved: bool = False,
    ) -> KnowledgeChunk:
        chunk = KnowledgeChunk(
            id=f"kchunk-{uuid4().hex[:12]}",
            campaign_id=campaign_id,
            source_id=source_id,
            content=content,
            position=position,
            char_start=char_start,
            char_end=char_end,
            approved=approved,
            created_at=_timestamp(),
        )
        with self._lock:
            self._knowledge_chunks[chunk.id] = chunk
            self._knowledge_chunks_by_source.setdefault(source_id, []).append(chunk.id)
        return chunk.model_copy(deep=True)

    def count_chunks_for_source(self, source_id: str) -> int:
        with self._lock:
            return len(self._knowledge_chunks_by_source.get(source_id, []))

    def get_knowledge_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        with self._lock:
            chunk = self._knowledge_chunks.get(chunk_id)
            return None if chunk is None else chunk.model_copy(deep=True)

    def search_knowledge_chunks(
        self,
        *,
        campaign_id: str,
        query: str,
        k: int,
    ) -> list[ChunkHit]:
        """Very small in-memory BM25 stand-in: ranks by normalized term overlap.

        The Surreal path uses the real ``BM25`` index. This stub exists so
        the InMemory test harness can exercise the retrieval surface
        without SurrealDB; it is not a replacement for real ranking.
        """
        terms = [term for term in _tokenize_query(query) if term]
        if not terms:
            return []
        hits: list[tuple[float, KnowledgeChunk]] = []
        with self._lock:
            for chunk_id in self._knowledge_chunks_by_source.get(campaign_id, []):  # kept empty in tests
                chunk = self._knowledge_chunks.get(chunk_id)
                if chunk is None or not chunk.approved:
                    continue
                tokens = _tokenize_query(chunk.content)
                overlap = sum(1 for term in terms if term in tokens)
                if overlap:
                    hits.append((overlap / max(len(terms), 1), chunk))
            hits.sort(key=lambda pair: pair[0], reverse=True)
        results: list[ChunkHit] = []
        for score, chunk in hits[:k]:
            source = self._knowledge_sources.get(chunk.source_id)
            results.append(
                ChunkHit(
                    chunk_id=chunk.id,
                    content=chunk.content,
                    source_id=chunk.source_id,
                    source_title=source.title if source else "",
                    score=score,
                    start_char=chunk.char_start,
                    end_char=chunk.char_end,
                )
            )
        return results

    def record_retrieval_audit(
        self,
        *,
        campaign_id: str,
        surface: Literal["designer", "interviewer"],
        query: str,
        top_k: int,
        chunk_ids: list[str],
        scores: list[float],
    ) -> RetrievalAuditRow:
        audit = RetrievalAuditRow(
            id=f"retaudit-{uuid4().hex[:12]}",
            campaign_id=campaign_id,
            surface=surface,
            query=query,
            top_k=top_k,
            chunk_ids=list(chunk_ids),
            scores=list(scores),
            created_at=_timestamp(),
        )
        with self._lock:
            self._retrieval_audits[audit.id] = audit
            self._retrieval_audits_by_campaign.setdefault(campaign_id, []).append(audit.id)
        return audit.model_copy(deep=True)

    def get_retrieval_audit(self, audit_id: str) -> RetrievalAuditRow | None:
        with self._lock:
            audit = self._retrieval_audits.get(audit_id)
            return None if audit is None else audit.model_copy(deep=True)


def _tokenize_query(text: str) -> list[str]:
    import re as _re
    return [token.lower() for token in _re.findall(r"[A-Za-z0-9]+", text or "")]


@lru_cache(maxsize=1)
def get_repository():
    from agentic_survey.config import get_settings

    settings = get_settings()
    if settings.repository == "surreal":
        from agentic_survey.db.surreal_repository import SurrealRepository

        return SurrealRepository(settings)
    return InMemoryRepository()

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from secrets import token_urlsafe
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from agentic_survey.domain.intent import BrainBIntent, QuestionCoverageStatus
from agentic_survey.domain.outline import (
    MicroFormField,
    OutlineArtifact,
    OutlineRubric,
    ParticipantFAQEntry,
)
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine.state_machine import CampaignState, transition_or_raise
from agentic_survey.llm.catalog import AGENT_ROLES, AgentRole as CatalogRole, CatalogEntry, seed_entries

ParticipantControl = Literal["pause", "skip", "continue", "stop"]
SharedContextKind = Literal[
    "study_context",
    "market_context",
    "technical_context",
    "aggregate_graph_context",
]


class DesignerTurn(BaseModel):
    id: str
    role: Literal["designer", "scientist"]
    content: str
    brain_b_intent: BrainBIntent | None = None
    get_user_input: GetUserInputOptions | None = None
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


RetrievalMode = Literal["bm25", "vector", "hybrid"]


class RetrievalAuditRow(BaseModel):
    id: str
    campaign_id: str
    surface: Literal["designer", "interviewer"]
    query: str
    top_k: int
    chunk_ids: list[str] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    mode: RetrievalMode = "hybrid"
    cache_hit: bool = False
    created_at: str


class QuestionAnswerRecord(BaseModel):
    id: str
    campaign_id: str
    session_id: str
    question_id: str
    status: QuestionCoverageStatus
    confidence: float
    evidence_quote: str = ""
    turn_id: str | None = None
    created_at: str
    updated_at: str


class ChunkHit(BaseModel):
    chunk_id: str
    content: str
    source_id: str
    source_title: str
    score: float
    start_char: int
    end_char: int


class Concept(BaseModel):
    """A unique (campaign, normalized-label) node in the knowledge graph.

    ``label`` is stored in its normalized (casefolded) form so the
    (campaign, label) uniqueness constraint is idempotent across
    validator outputs that vary capitalization or trailing whitespace.
    ``is_new`` is set only on the insert-path return from
    ``merge_concept`` and is never persisted; callers use it to decide
    whether a ``GraphDelta.add_nodes`` entry is warranted.
    """

    id: str
    campaign_id: str
    label: str
    type: str = ""
    mention_count: int = 0
    first_seen: str
    is_new: bool = False


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
    brain_b_intent: BrainBIntent | None = None
    get_user_input: GetUserInputOptions | None = None
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
    micro_form_answers: dict[str, str] = Field(default_factory=dict)
    turns: list[InterviewTurnRecord] = Field(default_factory=list)
    next_plan: BrainBIntent | None = None


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
        self._chunk_embeddings: dict[str, list[float]] = {}
        self._concepts: dict[str, Concept] = {}
        self._concept_by_label: dict[tuple[str, str], str] = {}
        self._concepts_by_campaign: dict[str, list[str]] = {}
        self._concept_embeddings: dict[str, list[float]] = {}
        self._graph_edges: list[dict] = []
        self._campaign_exports: list[dict] = []
        self._question_answers: dict[tuple[str, str], QuestionAnswerRecord] = {}
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
            if campaign.state in (CampaignState.DRAFT, CampaignState.REVIEWING):
                campaign.state = transition_or_raise(campaign.state, CampaignState.DESIGNING)
                campaign.outline_status = "collecting_brief"
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
        brain_b_intent: BrainBIntent | None = None,
        get_user_input: GetUserInputOptions | None = None,
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
        micro_form_answers: dict[str, str] | None = None,
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
            micro_form_answers=dict(micro_form_answers) if micro_form_answers else {},
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
        brain_b_intent: BrainBIntent | None = None,
        get_user_input: GetUserInputOptions | None = None,
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

    def update_next_plan(
        self,
        session_id: str,
        plan: BrainBIntent | None,
    ) -> InterviewSessionRecord:
        with self._lock:
            session = self._interview_sessions[session_id]
            session.next_plan = plan.model_copy(deep=True) if plan is not None else None
            session.updated_at = _timestamp()
        return session.model_copy(deep=True)

    def update_interview_turn_validation(
        self,
        session_id: str,
        turn_id: str,
        patch: dict,
    ) -> InterviewTurnRecord:
        """Merge ``patch`` into the turn's validation dict (creates if absent)."""
        with self._lock:
            session = self._interview_sessions[session_id]
            for turn in session.turns:
                if turn.id != turn_id:
                    continue
                current: dict = dict(turn.validation) if isinstance(turn.validation, dict) else {}
                current.update(patch)
                turn.validation = current
                session.updated_at = _timestamp()
                return turn.model_copy(deep=True)
        raise KeyError(f"Interview turn not found: session={session_id!r} turn={turn_id!r}")

    def upsert_question_answer(
        self,
        *,
        campaign_id: str,
        session_id: str,
        question_id: str,
        status: QuestionCoverageStatus,
        confidence: float,
        evidence_quote: str,
        turn_id: str | None,
    ) -> None:
        now = _timestamp()
        key = (session_id, question_id)
        with self._lock:
            existing = self._question_answers.get(key)
            if existing is None:
                self._question_answers[key] = QuestionAnswerRecord(
                    id=f"qans-{uuid4().hex[:12]}",
                    campaign_id=campaign_id,
                    session_id=session_id,
                    question_id=question_id,
                    status=status,
                    confidence=float(confidence),
                    evidence_quote=evidence_quote or "",
                    turn_id=turn_id or None,
                    created_at=now,
                    updated_at=now,
                )
                return
            existing.status = status
            existing.confidence = float(confidence)
            existing.evidence_quote = evidence_quote or ""
            existing.turn_id = turn_id or None
            existing.updated_at = now

    def list_question_answers_for_session(
        self, session_id: str
    ) -> list[QuestionAnswerRecord]:
        """Return question answers for a session, newest-updated first."""
        with self._lock:
            rows = [
                row.model_copy(deep=True)
                for row in self._question_answers.values()
                if row.session_id == session_id
            ]
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows

    def list_question_answers_for_campaign(
        self, campaign_id: str
    ) -> list[QuestionAnswerRecord]:
        """Return campaign question answers ordered by session id, then question id."""
        with self._lock:
            rows = [
                row.model_copy(deep=True)
                for row in self._question_answers.values()
                if row.campaign_id == campaign_id
            ]
        rows.sort(key=lambda row: (row.session_id, row.question_id))
        return rows

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
        error_detail: str | None = None,
    ) -> KnowledgeSource:
        with self._lock:
            source = self._knowledge_sources[source_id]
            source.status = status
            source.updated_at = _timestamp()
            if error_detail is not None:
                # Empty string explicitly clears; any other string sets.
                # ``None`` (the default) preserves the prior value so the UI
                # can show a tier-1-insufficient note through the tier-2
                # fallback until the source reaches ``pending_approval`` or
                # ``failed``.
                source.error_detail = error_detail or None
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

    def list_knowledge_sources_by_status(
        self,
        statuses: list[KnowledgeSourceStatus],
    ) -> list[KnowledgeSource]:
        """Cross-campaign list used by the ingestion worker.

        Sources are returned oldest-updated first so the worker drains the
        queue in FIFO order. An empty ``statuses`` returns nothing.
        """
        if not statuses:
            return []
        wanted = set(statuses)
        with self._lock:
            matched = [
                source.model_copy(deep=True)
                for source in self._knowledge_sources.values()
                if source.status in wanted
            ]
        matched.sort(key=lambda source: source.updated_at)
        return matched

    def list_knowledge_chunks_for_source(self, source_id: str) -> list[KnowledgeChunk]:
        with self._lock:
            ids = list(self._knowledge_chunks_by_source.get(source_id, []))
            chunks = [self._knowledge_chunks[cid].model_copy(deep=True) for cid in ids]
        chunks.sort(key=lambda c: c.position)
        return chunks

    def update_knowledge_chunk_embedding(
        self,
        chunk_id: str,
        embedding: list[float],
    ) -> None:
        """Attach a vector to an existing chunk.

        InMemory: stashed in a side map because ``KnowledgeChunk`` does
        not model the embedding (the Surreal row does). Tests that care
        about the side map read it via ``get_chunk_embedding``.
        """
        with self._lock:
            if chunk_id not in self._knowledge_chunks:
                raise KeyError(f"knowledge_chunk {chunk_id} not found")
            self._chunk_embeddings[chunk_id] = list(embedding)

    def get_chunk_embedding(self, chunk_id: str) -> list[float] | None:
        with self._lock:
            vec = self._chunk_embeddings.get(chunk_id)
            return list(vec) if vec is not None else None

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

    def search_knowledge_chunks_bm25(
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
        Iterates every chunk in the repository, filtered to
        ``campaign_id`` + ``approved=true``; the ``_knowledge_chunks_by_source``
        side map is keyed by ``source_id`` and cannot serve a
        campaign-scoped lookup.
        """
        terms = [term for term in _tokenize_query(query) if term]
        if not terms:
            return []
        hits: list[tuple[float, KnowledgeChunk]] = []
        with self._lock:
            for chunk in self._knowledge_chunks.values():
                if chunk.campaign_id != campaign_id or not chunk.approved:
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

    def search_knowledge_chunks_vector(
        self,
        *,
        campaign_id: str,
        vector: list[float],
        k: int,
    ) -> list[ChunkHit]:
        """In-memory brute cosine KNN over stored chunk embeddings.

        Iterates every chunk whose ``campaign_id`` matches and that is
        ``approved=true``. Chunks without a stored embedding are skipped
        (not counted as zero-similarity). Returns top-k by cosine
        similarity in descending order. Exists so the hybrid retrieval
        test harness can run without SurrealDB.
        """
        if k <= 0 or not vector:
            return []
        query_vec = [float(v) for v in vector]
        query_norm = _vector_norm(query_vec)
        if query_norm == 0.0:
            return []
        ranked: list[tuple[float, KnowledgeChunk]] = []
        with self._lock:
            for chunk in self._knowledge_chunks.values():
                if chunk.campaign_id != campaign_id or not chunk.approved:
                    continue
                chunk_vec = self._chunk_embeddings.get(chunk.id)
                if chunk_vec is None or not chunk_vec:
                    continue
                score = _cosine_similarity(
                    query_vec, chunk_vec, query_norm=query_norm
                )
                ranked.append((score, chunk))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        results: list[ChunkHit] = []
        for score, chunk in ranked[:k]:
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
        mode: str = "hybrid",
        cache_hit: bool = False,
    ) -> RetrievalAuditRow:
        audit = RetrievalAuditRow(
            id=f"retaudit-{uuid4().hex[:12]}",
            campaign_id=campaign_id,
            surface=surface,
            query=query,
            top_k=top_k,
            chunk_ids=list(chunk_ids),
            scores=list(scores),
            mode=mode,
            cache_hit=cache_hit,
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

    def list_retrieval_audits_for_campaign(
        self, campaign_id: str
    ) -> list[RetrievalAuditRow]:
        """All retrieval_audit rows for a campaign, oldest first.

        Feeds the M6 RAG export ``queries.jsonl`` dump; no runtime hot
        path uses this method. Sorted by ``created_at`` ascending so the
        on-disk artifact reads chronologically.
        """
        with self._lock:
            ids = list(self._retrieval_audits_by_campaign.get(campaign_id, []))
            rows = [self._retrieval_audits[aid].model_copy(deep=True) for aid in ids]
        rows.sort(key=lambda row: row.created_at)
        return rows

    # ------------------------------------------------------------------
    # Knowledge graph (M5).
    # ------------------------------------------------------------------

    async def merge_concept(
        self,
        *,
        campaign_id: str,
        label: str,
        type: str,
        router,
    ) -> Concept:
        """Idempotent upsert of a (campaign, normalized-label) concept node.

        First insert embeds the normalized label via :func:`embed_query`
        on the dynamo endpoint and stores the 768-dim vector in the side
        map. Re-mentions skip the embedding call and increment
        ``mention_count``. ``type`` is captured on first insert only; later
        mentions preserve the original type to keep the graph stable.
        """
        normalized = _normalize_concept_label(label)
        with self._lock:
            existing_id = self._concept_by_label.get((campaign_id, normalized))
            if existing_id is not None:
                concept = self._concepts[existing_id]
                concept.mention_count += 1
                return concept.model_copy(
                    update={"is_new": False}, deep=True
                )

        # First insert: embed, then persist. Embedding happens outside the
        # lock because it is an awaitable network call; the concurrent
        # "same label at same time" collision is handled below.
        from agentic_survey.services.retrieval_embed import embed_query

        vector = await embed_query(normalized, router=router)
        now = _timestamp()
        concept_id = f"concept-{uuid4().hex[:12]}"
        new_concept = Concept(
            id=concept_id,
            campaign_id=campaign_id,
            label=normalized,
            type=type or "",
            mention_count=1,
            first_seen=now,
        )
        with self._lock:
            existing_id = self._concept_by_label.get((campaign_id, normalized))
            if existing_id is not None:
                # Another caller inserted the same concept while we were
                # embedding. Drop our vector and bump the existing row.
                concept = self._concepts[existing_id]
                concept.mention_count += 1
                return concept.model_copy(
                    update={"is_new": False}, deep=True
                )
            self._concepts[concept_id] = new_concept
            self._concept_by_label[(campaign_id, normalized)] = concept_id
            self._concepts_by_campaign.setdefault(campaign_id, []).append(concept_id)
            self._concept_embeddings[concept_id] = list(vector)
        return new_concept.model_copy(update={"is_new": True}, deep=True)

    def record_mentioned_with(
        self,
        *,
        campaign_id: str,
        session_id: str,
        turn_id: str,
        from_id: str,
        to_id: str,
        kind: str,
        confidence: float,
    ) -> None:
        if kind not in ("co_occurrence", "explicit_relation"):
            raise ValueError(
                f"mentioned_with.kind must be co_occurrence or explicit_relation; got {kind!r}"
            )
        with self._lock:
            self._graph_edges.append(
                {
                    "id": f"edge-{uuid4().hex[:12]}",
                    "edge_table": "mentioned_with",
                    "campaign_id": campaign_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "from": from_id,
                    "to": to_id,
                    "kind": kind,
                    "confidence": float(confidence),
                    "created_at": _timestamp(),
                }
            )

    def record_contradicts(
        self,
        *,
        campaign_id: str,
        session_id: str,
        turn_id: str,
        from_id: str,
        to_id: str,
        confidence: float,
    ) -> None:
        with self._lock:
            self._graph_edges.append(
                {
                    "id": f"edge-{uuid4().hex[:12]}",
                    "edge_table": "contradicts",
                    "campaign_id": campaign_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "from": from_id,
                    "to": to_id,
                    "confidence": float(confidence),
                    "created_at": _timestamp(),
                }
            )

    def list_concept_neighborhood(
        self,
        *,
        campaign_id: str,
        label: str,
        k: int = 8,
        depth: int = 1,
    ) -> dict:
        """Depth-limited expansion around the concept matching ``label``.

        Returns ``{"center": concept|None, "nodes": [...], "edges": [...]}``.
        ``depth`` is clamped to [0, 2]; ``k`` caps total edges returned
        (newest first). Edges from both the ``mentioned_with`` and
        ``contradicts`` tables are considered. Missing labels return an
        empty response rather than raising so Brain B's tool call stays
        non-fatal when it probes a term we have not yet seen.
        """
        normalized = _normalize_concept_label(label)
        depth = max(0, min(int(depth), 2))
        k_cap = max(1, int(k))
        with self._lock:
            center_id = self._concept_by_label.get((campaign_id, normalized))
            if center_id is None:
                return {"center": None, "nodes": [], "edges": []}
            node_ids: set[str] = {center_id}
            frontier: set[str] = {center_id}
            collected_edges: list[dict] = []
            seen_edge_ids: set[str] = set()
            for _ in range(depth):
                next_frontier: set[str] = set()
                for edge in self._graph_edges:
                    if edge["campaign_id"] != campaign_id:
                        continue
                    if edge["id"] in seen_edge_ids:
                        continue
                    if edge["from"] in frontier or edge["to"] in frontier:
                        seen_edge_ids.add(edge["id"])
                        collected_edges.append(edge)
                        if edge["from"] not in node_ids:
                            next_frontier.add(edge["from"])
                        if edge["to"] not in node_ids:
                            next_frontier.add(edge["to"])
                node_ids.update(next_frontier)
                frontier = next_frontier
                if not frontier:
                    break
            collected_edges.sort(key=lambda e: e["created_at"], reverse=True)
            capped_edges = collected_edges[:k_cap]
            node_payload: list[dict] = []
            for node_id in node_ids:
                concept = self._concepts.get(node_id)
                if concept is None:
                    continue
                node_payload.append(
                    {
                        "id": concept.id,
                        "label": concept.label,
                        "type": concept.type,
                        "mention_count": concept.mention_count,
                        "first_seen": concept.first_seen,
                    }
                )
            edge_payload = [
                {
                    "from": edge["from"],
                    "to": edge["to"],
                    "kind": edge.get("kind", "contradicts" if edge["edge_table"] == "contradicts" else ""),
                    "edge_table": edge["edge_table"],
                    "confidence": edge["confidence"],
                    "session_id": edge["session_id"],
                    "turn_id": edge["turn_id"],
                    "created_at": edge["created_at"],
                }
                for edge in capped_edges
            ]
            center = self._concepts[center_id]
            return {
                "center": {
                    "id": center.id,
                    "label": center.label,
                    "type": center.type,
                    "mention_count": center.mention_count,
                    "first_seen": center.first_seen,
                },
                "nodes": node_payload,
                "edges": edge_payload,
            }

    def get_concept(self, concept_id: str) -> Concept | None:
        with self._lock:
            concept = self._concepts.get(concept_id)
            return None if concept is None else concept.model_copy(deep=True)

    def get_concept_embedding(self, concept_id: str) -> list[float] | None:
        with self._lock:
            vec = self._concept_embeddings.get(concept_id)
            return list(vec) if vec is not None else None

    def list_concepts_for_campaign(self, campaign_id: str) -> list[Concept]:
        """All concept rows for a campaign, ``first_seen`` ascending.

        M6 export feed. Returned copies drop the ``is_new`` flag so
        callers can treat the rows as snapshots.
        """
        with self._lock:
            ids = list(self._concepts_by_campaign.get(campaign_id, []))
            rows = [self._concepts[cid].model_copy(deep=True) for cid in ids]
        rows.sort(key=lambda row: row.first_seen)
        for row in rows:
            row.is_new = False
        return rows

    def list_graph_edges_for_campaign(self, campaign_id: str) -> list[dict]:
        """All ``mentioned_with`` + ``contradicts`` edges, newest first.

        Each row: ``{edge_table, from_id, to_id, kind, confidence,
        session_id, turn_id, created_at}``. ``kind`` is defaulted to
        ``"contradicts"`` for rows from the ``contradicts`` side list so
        the export graph carries a consistent shape.
        """
        with self._lock:
            filtered = [
                edge for edge in self._graph_edges if edge["campaign_id"] == campaign_id
            ]
        filtered.sort(key=lambda edge: edge["created_at"], reverse=True)
        return [
            {
                "edge_table": edge["edge_table"],
                "from_id": edge["from"],
                "to_id": edge["to"],
                "kind": edge.get(
                    "kind",
                    "contradicts" if edge["edge_table"] == "contradicts" else "",
                ),
                "confidence": edge["confidence"],
                "session_id": edge["session_id"],
                "turn_id": edge["turn_id"],
                "created_at": edge["created_at"],
            }
            for edge in filtered
        ]

    # ------------------------------------------------------------------
    # Campaign export (M6). Audit trail for the ./campaigns/{slug}/rag
    # folder sync; the on-disk artifact is not the source of truth.
    # ------------------------------------------------------------------

    def create_campaign_export(
        self,
        *,
        campaign_id: str,
        manifest: dict,
        export_path: str,
    ) -> str:
        export_id = f"cexport-{uuid4().hex[:12]}"
        now = _timestamp()
        with self._lock:
            self._campaign_exports.append(
                {
                    "id": export_id,
                    "campaign_id": campaign_id,
                    "manifest": dict(manifest),
                    "export_path": export_path,
                    "created_at": now,
                }
            )
        return export_id

    def list_campaign_exports_for_campaign(self, campaign_id: str) -> list[dict]:
        with self._lock:
            matches = [
                dict(row)
                for row in self._campaign_exports
                if row["campaign_id"] == campaign_id
            ]
        matches.sort(key=lambda row: row["created_at"])
        return matches

    def get_latest_campaign_export(self, campaign_id: str) -> dict | None:
        """Return the most recent ``campaign_export`` row for the campaign.

        Centralizes "latest manifest" lookup so the admin route does not
        open-code ``list(...)[-1]`` and silently break if ordering ever
        flips. Returns ``None`` when no sync has run yet.
        """
        exports = self.list_campaign_exports_for_campaign(campaign_id)
        return exports[-1] if exports else None


def _normalize_concept_label(raw: str) -> str:
    if raw is None:
        raise ValueError("concept label must be a non-empty string")
    normalized = raw.strip().casefold()
    if not normalized:
        raise ValueError("concept label must be a non-empty string")
    return normalized


def _tokenize_query(text: str) -> list[str]:
    import re as _re
    return [token.lower() for token in _re.findall(r"[A-Za-z0-9]+", text or "")]


def _vector_norm(vector: list[float]) -> float:
    import math as _math
    return _math.sqrt(sum(value * value for value in vector))


def _cosine_similarity(
    left: list[float],
    right: list[float],
    *,
    query_norm: float | None = None,
) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = query_norm if query_norm is not None else _vector_norm(left)
    right_norm = _vector_norm(right)
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


@lru_cache(maxsize=1)
def get_repository():
    from agentic_survey.config import get_settings

    settings = get_settings()
    if settings.repository == "surreal":
        from agentic_survey.db.surreal_repository import SurrealRepository

        return SurrealRepository(settings)
    return InMemoryRepository()

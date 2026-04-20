from __future__ import annotations

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from surrealdb import RecordID, Surreal

from agentic_survey.config import Settings
from agentic_survey.engine.state_machine import CampaignState, transition_or_raise
from agentic_survey.llm.catalog import AGENT_ROLES, AgentRole as CatalogRole, CatalogEntry, seed_entries
from agentic_survey.repository import (
    AdminSession,
    BrainIntentRecord,
    Campaign,
    DesignerSession,
    DesignerTurn,
    GetUserInputPayload,
    InMemoryRepository,
    InterviewSessionRecord,
    InterviewTurnRecord,
    Invite,
    OutlineArtifact,
    OutlineRevision,
    _default_participant_faq,
    _default_study_context,
    DEFAULT_AGGREGATE_GRAPH_CONTEXT,
    DEFAULT_MICRO_FORM_SCHEMA,
    DEFAULT_PERSONA_HINTS,
    DEFAULT_RUBRIC,
)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _timestamp() -> str:
    return _utcnow().isoformat()


def _ensure_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError(f"cannot coerce {type(value).__name__} to ISO timestamp")


def _to_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value)


def _record_id(table: str, raw: RecordID | str) -> str:
    if isinstance(raw, RecordID):
        return str(raw.id)
    if not isinstance(raw, str):
        raise TypeError(f"expected RecordID or str, got {type(raw).__name__}")
    prefix = f"{table}:"
    if raw.startswith(prefix):
        return raw[len(prefix):]
    return raw


def _normalize_rpc_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"ws", "wss", "http", "https"}:
        raise ValueError(f"unsupported SurrealDB URL scheme: {raw_url}")
    path = parsed.path or ""
    if not path.rstrip("/").endswith("/rpc"):
        path = (path.rstrip("/") + "/rpc").lstrip("/")
        path = f"/{path}" if not path.startswith("/") else path
    return urlunparse(parsed._replace(path=path))


def _catalog_key(catalog_id: str, role: CatalogRole) -> tuple[str, CatalogRole]:
    return (catalog_id, role)


def _campaign_id() -> str:
    return f"campaign-{uuid4().hex[:12]}"


def _designer_session_id() -> str:
    return f"designer-{uuid4().hex[:12]}"


def _interview_session_id() -> str:
    return f"session-{uuid4().hex[:12]}"


def _invite_id() -> str:
    return f"invite-{uuid4().hex[:12]}"


def _turn_id() -> str:
    return f"turn-{uuid4().hex[:12]}"


def _outline_revision_id() -> str:
    return f"outline-{uuid4().hex[:12]}"


def _build_default_outline(title: str, min_n: int, max_n: int) -> OutlineArtifact:
    consent_language = (
        "Participants choose anonymous or named participation at session start;"
        " named responses may be quoted in later study outputs."
    )
    scientist_summary = ""
    base_query = " ".join(part for part in title.split() if part).strip().lower()
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


def _outline_to_surreal(outline: OutlineArtifact) -> dict:
    payload = outline.model_dump()
    return payload


def _surreal_to_outline(row: dict) -> OutlineArtifact:
    return OutlineArtifact.model_validate(row)


class SurrealRepository:
    def __init__(self, settings: Settings) -> None:
        self._lock = RLock()
        self._settings = settings
        self._client: Surreal | None = None
        self._admin_sessions: dict[str, AdminSession] = {}
        self._catalog: dict[tuple[str, CatalogRole], CatalogEntry] = {}
        self._seed_catalog_locked()
        self._connect()

    def _connect(self) -> None:
        url = _normalize_rpc_url(self._settings.surreal_url)
        client = Surreal(url)
        client.signin({"username": self._settings.surreal_user, "password": self._settings.surreal_pass})
        client.use(self._settings.surreal_ns, self._settings.surreal_db)
        self._client = client

    def _db(self) -> Surreal:
        if self._client is None:
            self._connect()
        assert self._client is not None
        return self._client

    def _query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        return self._db().query(statement, variables or {})

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
                self._set_catalog_default_locked(stored.catalog_id, stored.role)
        return stored.model_copy(deep=True)

    def update_catalog_entry(self, catalog_id: str, role: CatalogRole, patch: dict) -> CatalogEntry:
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
                self._set_catalog_default_locked(catalog_id, role)
            return entry.model_copy(deep=True)

    def delete_catalog_entry(self, catalog_id: str, role: CatalogRole) -> None:
        with self._lock:
            key = _catalog_key(catalog_id, role)
            if key not in self._catalog:
                raise KeyError(f"Catalog entry not found for {catalog_id}/{role}")
            self._catalog.pop(key)

    def _set_catalog_default_locked(self, catalog_id: str, role: CatalogRole) -> None:
        timestamp = _timestamp()
        for entry in self._catalog.values():
            if entry.role != role:
                continue
            should_be_default = entry.catalog_id == catalog_id and entry.enabled
            if entry.is_default != should_be_default:
                entry.is_default = should_be_default
                entry.updated_at = timestamp

    def _require_catalog_selection_locked(self, role: str, catalog_id: str) -> CatalogEntry:
        entry = self._catalog.get(_catalog_key(catalog_id, role))  # type: ignore[arg-type]
        if entry is None:
            raise ValueError(f"Unknown catalog entry for role {role}: {catalog_id}")
        if not entry.enabled:
            raise ValueError(f"Catalog entry is disabled for role {role}: {catalog_id}")
        return entry

    @staticmethod
    def _validate_agent_role(role: str) -> None:
        if role not in AGENT_ROLES:
            allowed = ", ".join(AGENT_ROLES)
            raise ValueError(f"Unsupported agent role '{role}'. Expected one of: {allowed}")

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
        now_dt = _utcnow()
        now = now_dt.isoformat()
        normalized_agent_models = self._normalize_agent_models(agent_models)
        initial_outline = outline.model_copy(deep=True) if outline is not None else _build_default_outline(
            title=title, min_n=min_n, max_n=max_n,
        )
        campaign_id = _campaign_id()
        payload = {
            "title": title,
            "source": source,
            "state": state.value,
            "min_n": min_n,
            "max_n": max_n,
            "outline_status": outline_status,
            "outline": _outline_to_surreal(initial_outline),
            "agent_models": normalized_agent_models,
            "created_at": now_dt,
            "updated_at": now_dt,
        }
        self._db().create(RecordID("campaign", campaign_id), payload)
        revision = OutlineRevision(
            id=_outline_revision_id(),
            campaign_id=campaign_id,
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
        self._insert_outline_revision(campaign_id, revision)
        return self.get_campaign(campaign_id)  # type: ignore[return-value]

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        rows = self._db().select(RecordID("campaign", campaign_id))
        if not rows:
            return None
        return self._row_to_campaign(campaign_id, rows[0] if isinstance(rows, list) else rows)

    def list_campaigns(self) -> list[Campaign]:
        rows = self._query("SELECT * FROM campaign ORDER BY updated_at DESC;")
        campaigns = [self._row_to_campaign(_record_id("campaign", row["id"]), row) for row in rows]
        return campaigns

    def set_campaign_models(self, campaign_id: str, models: dict[str, str] | None) -> Campaign:
        normalized = self._normalize_agent_models(models)
        now_dt = _utcnow()
        self._query(
            "UPDATE type::thing('campaign', $id) MERGE { agent_models: $models, updated_at: $ts };",
            {"id": campaign_id, "models": normalized, "ts": now_dt},
        )
        return self.get_campaign(campaign_id)  # type: ignore[return-value]

    def update_campaign_models(self, campaign_id: str, patch: dict[str, str | None]) -> Campaign:
        campaign = self.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(f"Campaign not found: {campaign_id}")
        current = dict(campaign.agent_models or {})
        for role, catalog_id in patch.items():
            self._validate_agent_role(role)
            if catalog_id is None:
                current.pop(role, None)
                continue
            with self._lock:
                self._require_catalog_selection_locked(role, catalog_id)
            current[role] = catalog_id
        return self.set_campaign_models(campaign_id, current or None)

    def advance_campaign(self, campaign_id: str, target: CampaignState) -> Campaign:
        campaign = self.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(f"Campaign not found: {campaign_id}")
        new_state = transition_or_raise(campaign.state, target)
        now_dt = _utcnow()
        self._query(
            "UPDATE type::thing('campaign', $id) MERGE { state: $state, updated_at: $ts };",
            {"id": campaign_id, "state": new_state.value, "ts": now_dt},
        )
        return self.get_campaign(campaign_id)  # type: ignore[return-value]

    def get_designer_session(self, campaign_id: str) -> DesignerSession | None:
        rows = self._query(
            "SELECT * FROM designer_session WHERE campaign = type::thing('campaign', $id) LIMIT 1;",
            {"id": campaign_id},
        )
        if not rows:
            return None
        row = rows[0]
        session_id = _record_id("designer_session", row["id"])
        turns = self._query(
            "SELECT * FROM designer_turn WHERE session = type::thing('designer_session', $sid) ORDER BY created_at ASC;",
            {"sid": session_id},
        )
        return DesignerSession(
            id=session_id,
            campaign_id=campaign_id,
            status=row["status"],
            turns=[self._row_to_designer_turn(turn) for turn in turns],
            updated_at=_ensure_iso(row["updated_at"]),
        )

    def start_designer_session(self, campaign_id: str, opening_message: str) -> DesignerSession:
        campaign = self.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(f"Campaign not found: {campaign_id}")
        existing = self.get_designer_session(campaign_id)
        now_dt = _utcnow()
        now = now_dt.isoformat()
        if existing is None:
            session_id = _designer_session_id()
            self._db().create(
                RecordID("designer_session", session_id),
                {
                    "campaign": RecordID("campaign", campaign_id),
                    "status": "active",
                    "created_at": now_dt,
                    "updated_at": now_dt,
                },
            )
            self._append_designer_turn_raw(
                session_id=session_id,
                role="designer",
                content=opening_message,
                brain_b_intent=None,
                get_user_input=None,
                created_at_dt=now_dt,
                created_at=now,
            )
        else:
            session_id = existing.id
            self._query(
                "UPDATE type::thing('designer_session', $sid) MERGE { status: 'active', updated_at: $ts };",
                {"sid": session_id, "ts": now_dt},
            )
        if campaign.state == CampaignState.DRAFT:
            new_state = transition_or_raise(campaign.state, CampaignState.DESIGNING)
            self._query(
                "UPDATE type::thing('campaign', $id) MERGE { state: $state, updated_at: $ts };",
                {"id": campaign_id, "state": new_state.value, "ts": now_dt},
            )
        else:
            self._query(
                "UPDATE type::thing('campaign', $id) MERGE { updated_at: $ts };",
                {"id": campaign_id, "ts": now_dt},
            )
        session = self.get_designer_session(campaign_id)
        assert session is not None
        return session

    def append_designer_turn(
        self,
        campaign_id: str,
        role: Literal["designer", "scientist"],
        content: str,
        *,
        brain_b_intent: BrainIntentRecord | None = None,
        get_user_input: GetUserInputPayload | None = None,
    ) -> DesignerTurn:
        session = self.get_designer_session(campaign_id)
        if session is None:
            raise KeyError(f"Designer session not found for campaign {campaign_id}")
        now_dt = _utcnow()
        now = now_dt.isoformat()
        turn = self._append_designer_turn_raw(
            session_id=session.id,
            role=role,
            content=content,
            brain_b_intent=brain_b_intent,
            get_user_input=get_user_input,
            created_at_dt=now_dt,
            created_at=now,
        )
        self._query(
            "UPDATE type::thing('designer_session', $sid) MERGE { updated_at: $ts };",
            {"sid": session.id, "ts": now_dt},
        )
        self._query(
            "UPDATE type::thing('campaign', $id) MERGE { updated_at: $ts };",
            {"id": campaign_id, "ts": now_dt},
        )
        return turn

    def _append_designer_turn_raw(
        self,
        *,
        session_id: str,
        role: Literal["designer", "scientist"],
        content: str,
        brain_b_intent: BrainIntentRecord | None,
        get_user_input: GetUserInputPayload | None,
        created_at_dt: datetime,
        created_at: str,
    ) -> DesignerTurn:
        turn_id = _turn_id()
        self._db().create(
            RecordID("designer_turn", turn_id),
            {
                "session": RecordID("designer_session", session_id),
                "role": role,
                "content": content,
                "brain_b_intent": brain_b_intent.model_dump() if brain_b_intent is not None else None,
                "get_user_input": get_user_input.model_dump() if get_user_input is not None else None,
                "created_at": created_at_dt,
            },
        )
        return DesignerTurn(
            id=turn_id,
            role=role,
            content=content,
            brain_b_intent=brain_b_intent.model_copy(deep=True) if brain_b_intent is not None else None,
            get_user_input=get_user_input.model_copy(deep=True) if get_user_input is not None else None,
            created_at=created_at,
        )

    def update_outline(
        self,
        campaign_id: str,
        outline: OutlineArtifact,
        *,
        ready_for_review: bool,
    ) -> Campaign:
        previous = self.get_campaign(campaign_id)
        if previous is None:
            raise KeyError(f"Campaign not found: {campaign_id}")
        now_dt = _utcnow()
        now = now_dt.isoformat()
        outline_status = "ready_for_review" if ready_for_review else "collecting_brief"
        self._query(
            """UPDATE type::thing('campaign', $id) MERGE {
                outline: $outline,
                outline_status: $status,
                updated_at: $ts
            };""",
            {
                "id": campaign_id,
                "outline": _outline_to_surreal(outline),
                "status": outline_status,
                "ts": now_dt,
            },
        )
        session = self.get_designer_session(campaign_id)
        if session is not None:
            self._query(
                "UPDATE type::thing('designer_session', $sid) MERGE { status: $status, updated_at: $ts };",
                {"sid": session.id, "status": "ready_for_review" if ready_for_review else "active", "ts": now_dt},
            )
        changed = InMemoryRepository._changed_outline_sections(previous.outline, outline)
        if previous.outline_status != outline_status:
            changed.append("review_status")
        if changed:
            revision = OutlineRevision(
                id=_outline_revision_id(),
                campaign_id=campaign_id,
                source="designer",
                summary=InMemoryRepository._build_outline_revision_summary(changed, ready_for_review=ready_for_review),
                changed_sections=list(changed),
                outline=outline.model_copy(deep=True),
                created_at=now,
            )
            self._insert_outline_revision(campaign_id, revision)
        return self.get_campaign(campaign_id)  # type: ignore[return-value]

    def list_outline_revisions(self, campaign_id: str) -> list[OutlineRevision]:
        rows = self._query(
            "SELECT * FROM outline_revision WHERE campaign = type::thing('campaign', $id) ORDER BY created_at ASC;",
            {"id": campaign_id},
        )
        return [self._row_to_outline_revision(campaign_id, row) for row in rows]

    def _insert_outline_revision(self, campaign_id: str, revision: OutlineRevision) -> None:
        self._db().create(
            RecordID("outline_revision", revision.id),
            {
                "campaign": RecordID("campaign", campaign_id),
                "source": revision.source,
                "summary": revision.summary,
                "changed_sections": list(revision.changed_sections),
                "outline": _outline_to_surreal(revision.outline),
                "created_at": _to_dt(revision.created_at),
            },
        )

    def create_invite(self, campaign_id: str, label: str = "") -> Invite:
        invite_id = _invite_id()
        token = token_urlsafe(18)
        now_dt = _utcnow()
        now = now_dt.isoformat()
        self._db().create(
            RecordID("invite", invite_id),
            {
                "campaign": RecordID("campaign", campaign_id),
                "token": token,
                "label": label,
                "status": "active",
                "created_at": now_dt,
            },
        )
        return Invite(
            id=invite_id,
            campaign_id=campaign_id,
            token=token,
            label=label,
            status="active",
            created_at=now,
        )

    def list_invites(self, campaign_id: str) -> list[Invite]:
        rows = self._query(
            "SELECT * FROM invite WHERE campaign = type::thing('campaign', $id) ORDER BY created_at ASC;",
            {"id": campaign_id},
        )
        return [self._row_to_invite(row) for row in rows]

    def get_invite(self, invite_id: str) -> Invite | None:
        rows = self._db().select(RecordID("invite", invite_id))
        if not rows:
            return None
        row = rows[0] if isinstance(rows, list) else rows
        return self._row_to_invite(row)

    def get_invite_by_token(self, token: str) -> Invite | None:
        rows = self._query("SELECT * FROM invite WHERE token = $tok LIMIT 1;", {"tok": token})
        if not rows:
            return None
        return self._row_to_invite(rows[0])

    def mark_invite_used(self, invite_id: str, session_id: str) -> None:
        now_dt = _utcnow()
        self._query(
            """UPDATE type::thing('invite', $id) MERGE {
                status: 'used',
                used_at: $ts,
                session: type::thing('interview_session', $sid)
            };""",
            {"id": invite_id, "sid": session_id, "ts": now_dt},
        )

    def revoke_invite(self, invite_id: str) -> Invite | None:
        invite = self.get_invite(invite_id)
        if invite is None:
            return None
        now_dt = _utcnow()
        self._query(
            """UPDATE type::thing('invite', $id) MERGE {
                status: 'revoked',
                revoked_at: $ts,
                used_at: NONE,
                session: NONE
            };""",
            {"id": invite_id, "ts": now_dt},
        )
        return self.get_invite(invite_id)

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
        session_id = _interview_session_id()
        now_dt = _utcnow()
        now = now_dt.isoformat()
        participant_token = token_urlsafe(32)
        outline_rev = self._latest_outline_revision(campaign_id)
        if outline_rev is None:
            raise RuntimeError(f"No outline revision found for campaign {campaign_id}")
        payload: dict[str, Any] = {
            "campaign": RecordID("campaign", campaign_id),
            "invite": RecordID("invite", invite_id) if invite_id is not None else None,
            "participant_token": participant_token,
            "consent_mode": consent_mode,
            "identity_label": identity_label.strip()[:120],
            "persona_snapshot": persona_snapshot,
            "pinned_endpoint": pinned_endpoint,
            "outline_snapshot": RecordID("outline_revision", outline_rev.id),
            "status": "active",
            "started_at": now_dt,
            "updated_at": now_dt,
        }
        self._db().create(RecordID("interview_session", session_id), payload)
        return InterviewSessionRecord(
            id=session_id,
            campaign_id=campaign_id,
            invite_id=invite_id,
            participant_token=participant_token,
            consent_mode=consent_mode,
            identity_label=identity_label.strip()[:120],
            persona_snapshot=dict(persona_snapshot),
            pinned_endpoint=pinned_endpoint,
            status="active",
            started_at=now,
            updated_at=now,
        )

    def _latest_outline_revision(self, campaign_id: str) -> OutlineRevision | None:
        rows = self._query(
            "SELECT * FROM outline_revision WHERE campaign = type::thing('campaign', $id) ORDER BY created_at DESC LIMIT 1;",
            {"id": campaign_id},
        )
        if not rows:
            return None
        return self._row_to_outline_revision(campaign_id, rows[0])

    def get_interview_session(self, session_id: str) -> InterviewSessionRecord | None:
        rows = self._db().select(RecordID("interview_session", session_id))
        if not rows:
            return None
        row = rows[0] if isinstance(rows, list) else rows
        return self._row_to_interview_session(row, hydrate_turns=True)

    def get_interview_session_by_participant_token(self, token: str) -> InterviewSessionRecord | None:
        rows = self._query(
            "SELECT * FROM interview_session WHERE participant_token = $tok LIMIT 1;",
            {"tok": token},
        )
        if not rows:
            return None
        return self._row_to_interview_session(rows[0], hydrate_turns=True)

    def list_interview_sessions(self, campaign_id: str) -> list[InterviewSessionRecord]:
        rows = self._query(
            "SELECT * FROM interview_session WHERE campaign = type::thing('campaign', $id) ORDER BY started_at ASC;",
            {"id": campaign_id},
        )
        return [self._row_to_interview_session(row, hydrate_turns=True) for row in rows]

    def append_interview_turn(
        self,
        session_id: str,
        *,
        role: Literal["agent", "participant"],
        content: str,
        validation: dict | None = None,
        brain_b_intent: BrainIntentRecord | None = None,
        get_user_input: GetUserInputPayload | None = None,
    ) -> InterviewTurnRecord:
        session = self.get_interview_session(session_id)
        if session is None:
            raise KeyError(f"Interview session not found: {session_id}")
        turn_id = _turn_id()
        now_dt = _utcnow()
        now = now_dt.isoformat()
        index = len(session.turns)
        self._db().create(
            RecordID("interview_turn", turn_id),
            {
                "session": RecordID("interview_session", session_id),
                "role": role,
                "content": content,
                "index": index,
                "validation": validation,
                "brain_b_intent": brain_b_intent.model_dump() if brain_b_intent is not None else None,
                "get_user_input": get_user_input.model_dump() if get_user_input is not None else None,
                "created_at": now_dt,
            },
        )
        self._query(
            "UPDATE type::thing('interview_session', $sid) MERGE { updated_at: $ts };",
            {"sid": session_id, "ts": now_dt},
        )
        return InterviewTurnRecord(
            id=turn_id,
            session_id=session_id,
            role=role,
            content=content,
            index=index,
            validation=dict(validation) if validation is not None else None,
            brain_b_intent=brain_b_intent.model_copy(deep=True) if brain_b_intent is not None else None,
            get_user_input=get_user_input.model_copy(deep=True) if get_user_input is not None else None,
            created_at=now,
        )

    def pause_interview_session(self, session_id: str, *, reason: str) -> InterviewSessionRecord:
        now_dt = _utcnow()
        self._query(
            """UPDATE type::thing('interview_session', $sid) MERGE {
                status: 'paused',
                paused_reason: $reason,
                updated_at: $ts
            };""",
            {"sid": session_id, "reason": reason, "ts": now_dt},
        )
        session = self.get_interview_session(session_id)
        assert session is not None
        return session

    def resume_interview_session(self, session_id: str) -> InterviewSessionRecord:
        now_dt = _utcnow()
        self._query(
            """UPDATE type::thing('interview_session', $sid) MERGE {
                status: 'active',
                paused_reason: NONE,
                updated_at: $ts
            };""",
            {"sid": session_id, "ts": now_dt},
        )
        session = self.get_interview_session(session_id)
        assert session is not None
        return session

    def finish_interview_session(self, session_id: str, *, close_reason: str | None = None) -> InterviewSessionRecord:
        now_dt = _utcnow()
        self._query(
            """UPDATE type::thing('interview_session', $sid) MERGE {
                status: 'finished',
                finished_at: $ts,
                updated_at: $ts,
                close_reason: $reason,
                paused_reason: NONE
            };""",
            {"sid": session_id, "ts": now_dt, "reason": close_reason},
        )
        session = self.get_interview_session(session_id)
        assert session is not None
        return session

    def _row_to_campaign(self, campaign_id: str, row: dict) -> Campaign:
        return Campaign(
            id=campaign_id,
            title=row["title"],
            source=row.get("source", "blank"),
            state=CampaignState(row["state"]),
            min_n=int(row["min_n"]),
            max_n=int(row["max_n"]),
            outline_status=row.get("outline_status", "collecting_brief"),
            outline=_surreal_to_outline(row["outline"]),
            agent_models=row.get("agent_models"),
            created_at=_ensure_iso(row["created_at"]),
            updated_at=_ensure_iso(row["updated_at"]),
        )

    def _row_to_designer_turn(self, row: dict) -> DesignerTurn:
        return DesignerTurn(
            id=_record_id("designer_turn", row["id"]),
            role=row["role"],
            content=row["content"],
            brain_b_intent=BrainIntentRecord.model_validate(row["brain_b_intent"]) if row.get("brain_b_intent") else None,
            get_user_input=GetUserInputPayload.model_validate(row["get_user_input"]) if row.get("get_user_input") else None,
            created_at=_ensure_iso(row["created_at"]),
        )

    def _row_to_outline_revision(self, campaign_id: str, row: dict) -> OutlineRevision:
        return OutlineRevision(
            id=_record_id("outline_revision", row["id"]),
            campaign_id=campaign_id,
            source=row["source"],
            summary=row["summary"],
            changed_sections=list(row.get("changed_sections", [])),
            outline=_surreal_to_outline(row["outline"]),
            created_at=_ensure_iso(row["created_at"]),
        )

    def _row_to_invite(self, row: dict) -> Invite:
        return Invite(
            id=_record_id("invite", row["id"]),
            campaign_id=_record_id("campaign", row["campaign"]),
            token=row["token"],
            label=row.get("label", ""),
            status=row.get("status", "active"),
            created_at=_ensure_iso(row["created_at"]),
            used_at=_ensure_iso(row["used_at"]) if row.get("used_at") else None,
            session_id=_record_id("interview_session", row["session"]) if row.get("session") else None,
        )

    def _row_to_interview_session(self, row: dict, *, hydrate_turns: bool) -> InterviewSessionRecord:
        session_id = _record_id("interview_session", row["id"])
        turns: list[InterviewTurnRecord] = []
        if hydrate_turns:
            turn_rows = self._query(
                "SELECT * FROM interview_turn WHERE session = type::thing('interview_session', $sid) ORDER BY `index` ASC;",
                {"sid": session_id},
            )
            turns = [self._row_to_interview_turn(session_id, turn_row) for turn_row in turn_rows]
        return InterviewSessionRecord(
            id=session_id,
            campaign_id=_record_id("campaign", row["campaign"]),
            invite_id=_record_id("invite", row["invite"]) if row.get("invite") else None,
            participant_token=row["participant_token"],
            consent_mode=row["consent_mode"],
            identity_label=row.get("identity_label", ""),
            persona_snapshot=dict(row.get("persona_snapshot") or {}),
            pinned_endpoint=row["pinned_endpoint"],
            status=row["status"],
            started_at=_ensure_iso(row["started_at"]),
            updated_at=_ensure_iso(row["updated_at"]),
            finished_at=_ensure_iso(row["finished_at"]) if row.get("finished_at") else None,
            close_reason=row.get("close_reason"),
            paused_reason=row.get("paused_reason"),
            abandoned_reason=row.get("abandoned_reason"),
            turns=turns,
        )

    def _row_to_interview_turn(self, session_id: str, row: dict) -> InterviewTurnRecord:
        return InterviewTurnRecord(
            id=_record_id("interview_turn", row["id"]),
            session_id=session_id,
            role=row["role"],
            content=row["content"],
            index=int(row.get("index", 0)),
            validation=dict(row["validation"]) if row.get("validation") else None,
            brain_b_intent=BrainIntentRecord.model_validate(row["brain_b_intent"]) if row.get("brain_b_intent") else None,
            get_user_input=GetUserInputPayload.model_validate(row["get_user_input"]) if row.get("get_user_input") else None,
            created_at=_ensure_iso(row["created_at"]),
        )

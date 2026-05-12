import csv
import io
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import StreamingResponse

from agentic_survey.agents.brain_b_interviewer import filter_question_bank_for_role
from agentic_survey.auth import (
    clear_admin_session_cookie,
    get_admin_session_from_request,
    require_admin_session,
    set_admin_session_cookie,
)
from agentic_survey.config import Settings, get_settings
from agentic_survey.domain.observation import MethodObservation
from agentic_survey.domain.outline import SurveyQuestion
from agentic_survey.engine.event_bus import get_event_bus
from agentic_survey.repository import (
    AdminSession,
    InMemoryRepository,
    InterviewSessionRecord,
    LLMAuditRecord,
    QuestionAnswerRecord,
    get_repository,
)
from agentic_survey.services.rag_export import sync_campaign_rag_folder

router = APIRouter(prefix="/admin", tags=["admin"])


class TurnRetrievalAudit(BaseModel):
    retrieval_audit_id: str | None = None
    retrieval_audit_ids: list[str] = Field(default_factory=list)
    query: str = ""
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    audits: list[dict[str, Any]] = Field(default_factory=list)


class SessionPreplanAudit(BaseModel):
    status: str = "pending"
    error_detail: str | None = None
    inflight: bool = False


class TurnAuditResponse(BaseModel):
    turn_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    brain_b_intent: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    validator_result: dict[str, Any] | None = None
    retrieval: TurnRetrievalAudit
    preplan: SessionPreplanAudit
    llm_audits: list[LLMAuditRecord] = Field(default_factory=list)


class InterviewEventListResponse(BaseModel):
    items: list[dict[str, Any]]


class LLMAuditListResponse(BaseModel):
    items: list[LLMAuditRecord]


class AdminLoginRequest(BaseModel):
    password: str


class AdminSessionResponse(BaseModel):
    authenticated: bool
    expires_at: str | None = None


class MethodObservationCreateRequest(BaseModel):
    body: str
    tags: list[str] | None = None


class MethodObservationListResponse(BaseModel):
    observations: list[MethodObservation]


_ANSWER_EXPORT_COLUMNS = [
    "session_id",
    "identity_label",
    "consent_mode",
    "started_at",
    "finished_at",
    "role_self_description",
    "evidence_of_belonging",
    "question_id",
    "tier",
    "axis_tag",
    "applies_to_roles",
    "status",
    "confidence",
    "evidence_quote",
    "turn_id",
    "prompt",
]


@router.post("/login")
async def login(
    payload: AdminLoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> AdminSessionResponse:
    if payload.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session = repository.create_admin_session(ttl_hours=settings.admin_session_ttl_hours)
    set_admin_session_cookie(response, session.token, settings)
    return _session_response(session)


@router.get("/session")
async def get_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> AdminSessionResponse:
    session = get_admin_session_from_request(request, settings, repository)
    if session is None:
        return AdminSessionResponse(authenticated=False, expires_at=None)
    return _session_response(session)


@router.post("/logout")
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AdminSession = Depends(require_admin_session),
    repository: InMemoryRepository = Depends(get_repository),
) -> dict[str, bool]:
    repository.revoke_admin_session(session.token)
    clear_admin_session_cookie(response, settings)
    return {"ok": True}


def _session_response(session: AdminSession) -> AdminSessionResponse:
    return AdminSessionResponse(
        authenticated=True,
        expires_at=session.expires_at.isoformat(),
    )


def _method_observation_id() -> str:
    return f"mobs-{uuid4().hex[:12]}"


def _admin_author(session: AdminSession) -> str:
    raw = getattr(session, "username", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "operator"


def _require_campaign_session(
    *,
    campaign_id: str,
    session_id: str,
    repository: InMemoryRepository,
) -> InterviewSessionRecord:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    session = repository.get_interview_session(session_id)
    if session is None or session.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Session not found for this campaign")
    return session


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/observations")
async def create_method_observation(
    campaign_id: str,
    session_id: str,
    payload: MethodObservationCreateRequest,
    admin_session: AdminSession = Depends(require_admin_session),
    repository: InMemoryRepository = Depends(get_repository),
) -> MethodObservation:
    _require_campaign_session(
        campaign_id=campaign_id,
        session_id=session_id,
        repository=repository,
    )
    try:
        observation = MethodObservation(
            id=_method_observation_id(),
            session_id=session_id,
            campaign_id=campaign_id,
            author=_admin_author(admin_session),
            body=payload.body,
            tags=payload.tags,
            created_at=datetime.now(tz=UTC),
        )
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise HTTPException(
            status_code=400,
            detail=first.get("msg") or "Invalid observation",
        ) from exc
    return await repository.append_method_observation(observation)


@router.get("/campaigns/{campaign_id}/sessions/{session_id}/observations")
async def list_session_method_observations(
    campaign_id: str,
    session_id: str,
    _admin_session: AdminSession = Depends(require_admin_session),
    repository: InMemoryRepository = Depends(get_repository),
) -> MethodObservationListResponse:
    _require_campaign_session(
        campaign_id=campaign_id,
        session_id=session_id,
        repository=repository,
    )
    observations = await repository.list_method_observations(session_id=session_id)
    return MethodObservationListResponse(observations=observations)


@router.get("/campaigns/{campaign_id}/observations.jsonl")
async def stream_campaign_method_observations_jsonl(
    campaign_id: str,
    _admin_session: AdminSession = Depends(require_admin_session),
    repository: InMemoryRepository = Depends(get_repository),
) -> Response:
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    rows = await repository.list_campaign_method_observations(campaign_id=campaign_id)
    content = "".join(
        json.dumps(observation.model_dump(mode="json"), ensure_ascii=False) + "\n"
        for observation in rows
    )
    return Response(content=content, media_type="text/plain")


@router.get(
    "/campaigns/{campaign_id}/answers.csv",
    dependencies=[Depends(require_admin_session)],
)
async def stream_campaign_answers_csv(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> StreamingResponse:
    """Stream one row per eligible session and question pair as CSV.

    Sessions get rows only for questions eligible for that participant's
    role_self_description. Ineligible questions are omitted. Eligible questions
    with no durable answer row are emitted as pending with empty evidence cells.
    """
    rows = _answer_export_rows(campaign_id, repository)

    def generate() -> Iterable[str]:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=_ANSWER_EXPORT_COLUMNS)
        writer.writeheader()
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={
            "content-disposition": f'attachment; filename="{campaign_id}-answers.csv"'
        },
    )


@router.get(
    "/campaigns/{campaign_id}/answers.jsonl",
    dependencies=[Depends(require_admin_session)],
)
async def stream_campaign_answers_jsonl(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> StreamingResponse:
    """Stream one JSON object per eligible session and question pair.

    Sessions get rows only for questions eligible for that participant's
    role_self_description. Ineligible questions are omitted. Eligible questions
    with no durable answer row are emitted as pending with empty evidence cells.
    """
    rows = _answer_export_rows(campaign_id, repository)

    def generate() -> Iterable[str]:
        for row in rows:
            yield json.dumps(row, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
    )


def _answer_export_rows(
    campaign_id: str,
    repository: InMemoryRepository,
) -> Iterable[dict[str, Any]]:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    sessions = repository.list_interview_sessions(campaign_id)
    answers = repository.list_question_answers_for_campaign(campaign_id)
    answer_by_session_question = {
        (answer.session_id, answer.question_id): answer for answer in answers
    }
    return _iter_answer_export_rows(
        question_bank=campaign.outline.question_bank,
        sessions=sessions,
        answer_by_session_question=answer_by_session_question,
    )


def _iter_answer_export_rows(
    *,
    question_bank: list[SurveyQuestion],
    sessions: list[InterviewSessionRecord],
    answer_by_session_question: dict[tuple[str, str], QuestionAnswerRecord],
) -> Iterable[dict[str, Any]]:
    for session in sessions:
        role_self_description = (session.micro_form_answers or {}).get(
            "role_self_description",
            "",
        )
        eligible_questions = filter_question_bank_for_role(
            question_bank,
            role_self_description,
        )
        for question in eligible_questions:
            answer = answer_by_session_question.get((session.id, question.id))
            yield _answer_export_row(
                session=session,
                question=question,
                answer=answer,
            )


def _answer_export_row(
    *,
    session: InterviewSessionRecord,
    question: SurveyQuestion,
    answer: QuestionAnswerRecord | None,
) -> dict[str, Any]:
    answers = session.micro_form_answers or {}
    return {
        "session_id": session.id,
        "identity_label": session.identity_label,
        "consent_mode": session.consent_mode,
        "started_at": session.started_at,
        "finished_at": session.finished_at or "",
        "role_self_description": answers.get("role_self_description", ""),
        "evidence_of_belonging": answers.get("evidence_of_belonging", ""),
        "question_id": question.id,
        "tier": question.tier,
        "axis_tag": question.axis_tag,
        "applies_to_roles": "; ".join(question.applies_to_roles),
        "status": answer.status if answer is not None else "pending",
        "confidence": answer.confidence if answer is not None else 0,
        "evidence_quote": answer.evidence_quote if answer is not None else "",
        "turn_id": answer.turn_id if answer is not None and answer.turn_id else "",
        "prompt": question.prompt,
    }


@router.get(
    "/campaigns/{campaign_id}/sessions/{session_id}/turns/{turn_id}/audit",
    dependencies=[Depends(require_admin_session)],
)
async def get_turn_audit(
    campaign_id: str,
    session_id: str,
    turn_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> TurnAuditResponse:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    session = repository.get_interview_session(session_id)
    if session is None or session.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Session not found for this campaign")
    turn = next((t for t in session.turns if t.id == turn_id), None)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found for this session")

    brain_b_intent_payload = (
        turn.brain_b_intent.model_dump() if turn.brain_b_intent is not None else None
    )
    validator_result = repository.get_validator_result(turn.id)
    retrieval_rows: list[dict[str, Any]] = []
    retrieval_scores: list[float] = []
    retrieval_query = ""
    retrieval_audits: list[dict[str, Any]] = []
    retrieval_audit_ids = _turn_retrieval_audit_ids(turn)
    for audit_id in retrieval_audit_ids:
        audit = repository.get_retrieval_audit(audit_id)
        if audit is not None:
            if not retrieval_query:
                retrieval_query = audit.query
            retrieval_scores.extend(audit.scores)
            audit_chunks = [
                _retrieval_chunk_payload(repository, chunk_id)
                for chunk_id in audit.chunk_ids
            ]
            retrieval_rows.extend(audit_chunks)
            retrieval_audits.append(
                {
                    "retrieval_audit_id": audit.id,
                    "query": audit.query,
                    "mode": audit.mode,
                    "cache_hit": audit.cache_hit,
                    "chunks": audit_chunks,
                    "scores": list(audit.scores),
                }
            )
    if not retrieval_rows and turn.brain_b_intent is not None:
        for chunk_id in turn.brain_b_intent.retrieval_chunks or []:
            retrieval_rows.append(_retrieval_chunk_payload(repository, chunk_id))

    return TurnAuditResponse(
        turn_id=turn.id,
        session_id=turn.session_id,
        role=turn.role,
        content=turn.content,
        created_at=turn.created_at,
        brain_b_intent=brain_b_intent_payload,
        validation=turn.validation,
        validator_result=(
            validator_result.model_dump() if validator_result is not None else None
        ),
        retrieval=TurnRetrievalAudit(
            retrieval_audit_id=turn.retrieval_audit_id or (retrieval_audit_ids[-1] if retrieval_audit_ids else None),
            retrieval_audit_ids=retrieval_audit_ids,
            query=retrieval_query,
            chunks=retrieval_rows,
            scores=retrieval_scores,
            audits=retrieval_audits,
        ),
        preplan=SessionPreplanAudit(
            status=session.preplan_status,
            error_detail=session.preplan_error_detail,
            inflight=session.preplan_inflight,
        ),
        llm_audits=repository.list_llm_audits(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            limit=50,
        ),
    )


@router.get(
    "/campaigns/{campaign_id}/events",
    dependencies=[Depends(require_admin_session)],
)
async def list_campaign_interview_events(
    campaign_id: str,
    session_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 200,
    repository: InMemoryRepository = Depends(get_repository),
) -> InterviewEventListResponse:
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if session_id is not None:
        session = repository.get_interview_session(session_id)
        if session is None or session.campaign_id != campaign_id:
            raise HTTPException(status_code=404, detail="Session not found for this campaign")
    rows = repository.list_interview_events_for_campaign(
        campaign_id,
        session_id=session_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return InterviewEventListResponse(
        items=[row.model_dump(mode="json") for row in rows],
    )


@router.get(
    "/campaigns/{campaign_id}/sessions/{session_id}/events",
    dependencies=[Depends(require_admin_session)],
)
async def list_session_interview_events(
    campaign_id: str,
    session_id: str,
    after_sequence: int | None = None,
    limit: int = 200,
    repository: InMemoryRepository = Depends(get_repository),
) -> InterviewEventListResponse:
    _require_campaign_session(
        campaign_id=campaign_id,
        session_id=session_id,
        repository=repository,
    )
    rows = repository.list_interview_events_for_session(
        session_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return InterviewEventListResponse(
        items=[row.model_dump(mode="json") for row in rows],
    )


@router.get(
    "/campaigns/{campaign_id}/llm-audits",
    dependencies=[Depends(require_admin_session)],
)
async def list_campaign_llm_audits(
    campaign_id: str,
    session_id: str | None = None,
    turn_id: str | None = None,
    limit: int = 200,
    repository: InMemoryRepository = Depends(get_repository),
) -> LLMAuditListResponse:
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if session_id is not None:
        session = repository.get_interview_session(session_id)
        if session is None or session.campaign_id != campaign_id:
            raise HTTPException(status_code=404, detail="Session not found for this campaign")
    return LLMAuditListResponse(
        items=repository.list_llm_audits(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            limit=limit,
        )
    )


@router.get(
    "/campaigns/{campaign_id}/sessions/{session_id}/llm-audits",
    dependencies=[Depends(require_admin_session)],
)
async def list_session_llm_audits(
    campaign_id: str,
    session_id: str,
    turn_id: str | None = None,
    limit: int = 200,
    repository: InMemoryRepository = Depends(get_repository),
) -> LLMAuditListResponse:
    _require_campaign_session(
        campaign_id=campaign_id,
        session_id=session_id,
        repository=repository,
    )
    return LLMAuditListResponse(
        items=repository.list_llm_audits(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            limit=limit,
        )
    )


def _turn_retrieval_audit_ids(turn: Any) -> list[str]:
    ids: list[str] = []
    if turn.retrieval_audit_id:
        ids.append(turn.retrieval_audit_id)
    intent = getattr(turn, "brain_b_intent", None)
    if intent is not None:
        ids.extend(getattr(intent, "retrieval_audit_ids", []) or [])
    return list(dict.fromkeys(ids))


def _retrieval_chunk_payload(repository: InMemoryRepository, chunk_id: str) -> dict[str, Any]:
    chunk = repository.get_knowledge_chunk(chunk_id) if hasattr(repository, "get_knowledge_chunk") else None
    if chunk is None:
        return {"id": chunk_id, "content": "", "source": {"title": "", "url": None}}
    source = repository.get_knowledge_source(chunk.source_id)
    return {
        "id": chunk.id,
        "content": chunk.content,
        "source": {
            "id": chunk.source_id,
            "title": source.title if source else "",
            "url": source.url if source else None,
        },
    }


class SessionPreplanSummaryResponse(BaseModel):
    session_id: str
    campaign_id: str
    preplan: SessionPreplanAudit


@router.get(
    "/campaigns/{campaign_id}/sessions/{session_id}/preplan",
    dependencies=[Depends(require_admin_session)],
)
async def get_session_preplan_summary(
    campaign_id: str,
    session_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> SessionPreplanSummaryResponse:
    """Operator-facing summary of the pre-plan warmup state.

    Useful when inspecting a session that booted via invite redemption
    to check whether the eager Brain B warmup landed before the
    participant's first foreground turn arrived.
    """
    session = _require_campaign_session(
        campaign_id=campaign_id,
        session_id=session_id,
        repository=repository,
    )
    return SessionPreplanSummaryResponse(
        session_id=session.id,
        campaign_id=session.campaign_id,
        preplan=SessionPreplanAudit(
            status=session.preplan_status,
            error_detail=session.preplan_error_detail,
            inflight=session.preplan_inflight,
        ),
    )


class RagSyncResponse(BaseModel):
    campaign_id: str
    export_path: str
    files: dict[str, str]
    synced_at: str


@router.post(
    "/campaigns/{campaign_id}/rag/sync",
    dependencies=[Depends(require_admin_session)],
)
async def sync_campaign_rag(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> RagSyncResponse:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    rag_dir = await sync_campaign_rag_folder(
        campaign_id=campaign_id,
        repository=repository,
    )
    latest = repository.get_latest_campaign_export(campaign_id)
    # ``sync_campaign_rag_folder`` writes the manifest before returning, so
    # the route always sees a populated row. An empty manifest would mean
    # the writer skipped the export audit, which is a bug we want visible.
    synced_at = (latest or {}).get("manifest", {}).get("synced_at", "")
    return RagSyncResponse(
        campaign_id=campaign_id,
        export_path=str(rag_dir),
        files={
            "sources": str(rag_dir / "sources.jsonl"),
            "chunks": str(rag_dir / "chunks"),
            "queries": str(rag_dir / "queries.jsonl"),
            "graph": str(rag_dir / "graph.json"),
            "readme": str(rag_dir / "README.md"),
        },
        synced_at=synced_at,
    )


class GraphNode(BaseModel):
    id: str
    label: str
    type: str = ""
    first_seen: str
    mention_count: int


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    edge_table: str
    kind: str = ""
    confidence: float
    session_id: str
    turn_id: str
    created_at: str


class GraphSnapshotResponse(BaseModel):
    campaign_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    latest_event_seq: int


@router.get(
    "/campaigns/{campaign_id}/graph",
    dependencies=[Depends(require_admin_session)],
)
async def get_campaign_graph_snapshot(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> GraphSnapshotResponse:
    """Static snapshot of the campaign knowledge graph.

    The graph view fetches this on mount, then subscribes to
    ``/api/campaigns/{id}/stream`` with ``?since=latest_event_seq`` so it
    only receives events that landed after the snapshot was built. Edges
    come back newest-first; nodes in insertion order.
    """
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    concepts = repository.list_concepts_for_campaign(campaign_id)
    edges_raw = repository.list_graph_edges_for_campaign(campaign_id)
    nodes = [
        GraphNode(
            id=c.id,
            label=c.label,
            type=c.type,
            first_seen=c.first_seen,
            mention_count=c.mention_count,
        )
        for c in concepts
    ]
    edges = [
        GraphEdge(
            from_id=e["from_id"],
            to_id=e["to_id"],
            edge_table=e["edge_table"],
            kind=e.get("kind", ""),
            confidence=float(e["confidence"]),
            session_id=e["session_id"],
            turn_id=e["turn_id"],
            created_at=e["created_at"],
        )
        for e in edges_raw
    ]
    return GraphSnapshotResponse(
        campaign_id=campaign_id,
        nodes=nodes,
        edges=edges,
        latest_event_seq=max(
            get_event_bus().latest_seq(campaign_id),
            repository.latest_interview_event_sequence(campaign_id),
        ),
    )

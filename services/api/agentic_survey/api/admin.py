from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from agentic_survey.auth import (
    clear_admin_session_cookie,
    get_admin_session_from_request,
    require_admin_session,
    set_admin_session_cookie,
)
from agentic_survey.config import Settings, get_settings
from agentic_survey.repository import AdminSession, InMemoryRepository, get_repository
from agentic_survey.services.rag_export import sync_campaign_rag_folder

router = APIRouter(prefix="/admin", tags=["admin"])


class TurnRetrievalAudit(BaseModel):
    retrieval_audit_id: str | None = None
    query: str = ""
    chunks: list[dict[str, Any]] = []
    scores: list[float] = []


class TurnAuditResponse(BaseModel):
    turn_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    brain_b_intent: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    retrieval: TurnRetrievalAudit


class AdminLoginRequest(BaseModel):
    password: str


class AdminSessionResponse(BaseModel):
    authenticated: bool
    expires_at: str | None = None


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
    retrieval_rows: list[dict[str, Any]] = []
    retrieval_scores: list[float] = []
    retrieval_query = ""
    if turn.retrieval_audit_id is not None:
        audit = repository.get_retrieval_audit(turn.retrieval_audit_id)
        if audit is not None:
            retrieval_query = audit.query
            retrieval_scores = list(audit.scores)
            for chunk_id in audit.chunk_ids:
                chunk = repository.get_knowledge_chunk(chunk_id)
                if chunk is None:
                    retrieval_rows.append({"id": chunk_id, "content": "", "source": {"title": "", "url": None}})
                    continue
                source = repository.get_knowledge_source(chunk.source_id)
                retrieval_rows.append(
                    {
                        "id": chunk.id,
                        "content": chunk.content,
                        "source": {
                            "id": chunk.source_id,
                            "title": source.title if source else "",
                            "url": source.url if source else None,
                        },
                    }
                )
    elif turn.brain_b_intent is not None:
        for chunk_id in turn.brain_b_intent.retrieval_chunks or []:
            chunk = repository.get_knowledge_chunk(chunk_id) if hasattr(repository, "get_knowledge_chunk") else None
            if chunk is None:
                retrieval_rows.append({"id": chunk_id, "content": "", "source": {"title": "", "url": None}})
                continue
            source = repository.get_knowledge_source(chunk.source_id)
            retrieval_rows.append(
                {
                    "id": chunk.id,
                    "content": chunk.content,
                    "source": {
                        "id": chunk.source_id,
                        "title": source.title if source else "",
                        "url": source.url if source else None,
                    },
                }
            )

    return TurnAuditResponse(
        turn_id=turn.id,
        session_id=turn.session_id,
        role=turn.role,
        content=turn.content,
        created_at=turn.created_at,
        brain_b_intent=brain_b_intent_payload,
        validation=turn.validation,
        retrieval=TurnRetrievalAudit(
            retrieval_audit_id=turn.retrieval_audit_id,
            query=retrieval_query,
            chunks=retrieval_rows,
            scores=retrieval_scores,
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

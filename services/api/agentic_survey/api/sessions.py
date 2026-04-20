from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agentic_survey.agents.validator import Validator
from agentic_survey.auth import (
    get_admin_session_from_request,
    get_participant_session_from_request,
    require_admin_session,
)
from agentic_survey.config import Settings, get_settings
from agentic_survey.engine.interview_loop import (
    opening_turn_message,
    run_interview_turn,
)
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.llm.client import get_llm_client
from agentic_survey.llm.router import get_litellm_router
from agentic_survey.repository import (
    Campaign,
    InMemoryRepository,
    InterviewSessionRecord,
    get_repository,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


_llm_client = get_llm_client()
_validator = Validator(llm=_llm_client)
_retrieval_cache = RetrievalCache()


class ParticipantTurnRequest(BaseModel):
    content: str = Field(min_length=1)
    chip_selected: str | None = None


class SessionBundleResponse(BaseModel):
    session: InterviewSessionRecord
    campaign: Campaign


def _require_session_access(
    request: Request,
    session_id: str,
    settings: Settings,
    repository: InMemoryRepository,
) -> InterviewSessionRecord:
    session = repository.get_interview_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    participant = get_participant_session_from_request(request, settings, repository)
    if participant is not None and participant.id == session.id:
        return session
    admin = get_admin_session_from_request(request, settings, repository)
    if admin is not None:
        return session
    raise HTTPException(status_code=401, detail="Session access denied")


def _load_campaign(repository: InMemoryRepository, campaign_id: str) -> Campaign:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("/me")
async def get_my_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> SessionBundleResponse:
    session = get_participant_session_from_request(request, settings, repository)
    if session is None:
        raise HTTPException(status_code=404, detail="No participant session in progress")
    campaign = _load_campaign(repository, session.campaign_id)
    return SessionBundleResponse(session=session, campaign=campaign)


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> SessionBundleResponse:
    session = _require_session_access(request, session_id, settings, repository)
    campaign = _load_campaign(repository, session.campaign_id)
    return SessionBundleResponse(session=session, campaign=campaign)


@router.post("/{session_id}/start")
async def start_participant_loop(
    session_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> SessionBundleResponse:
    session = _require_session_access(request, session_id, settings, repository)
    campaign = _load_campaign(repository, session.campaign_id)
    if session.turns:
        return SessionBundleResponse(session=session, campaign=campaign)

    repository.append_interview_turn(
        session.id,
        role="agent",
        content=opening_turn_message(campaign),
    )
    session = repository.get_interview_session(session.id)  # type: ignore[assignment]
    assert session is not None
    return SessionBundleResponse(session=session, campaign=campaign)


@router.post("/{session_id}/resume")
async def resume_participant_loop(
    session_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> SessionBundleResponse:
    session = _require_session_access(request, session_id, settings, repository)
    campaign = _load_campaign(repository, session.campaign_id)
    if session.status == "finished":
        raise HTTPException(status_code=409, detail="Session is already finished")
    if session.status == "abandoned":
        raise HTTPException(status_code=409, detail="Session has been abandoned")
    if session.status == "paused":
        session = repository.resume_interview_session(session.id)
    return SessionBundleResponse(session=session, campaign=campaign)


@router.post("/{session_id}/turns")
async def submit_participant_turn(
    session_id: str,
    payload: ParticipantTurnRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> SessionBundleResponse:
    session = _require_session_access(request, session_id, settings, repository)
    if session.status == "paused":
        raise HTTPException(status_code=409, detail="Session is paused")
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session is no longer active")
    campaign = _load_campaign(repository, session.campaign_id)

    result = await run_interview_turn(
        session_id=session.id,
        participant_content=payload.content,
        chip_selected=payload.chip_selected,
        repository=repository,
        validator=_validator,
        router=get_litellm_router(),
        cache=_retrieval_cache,
    )

    return SessionBundleResponse(session=result.session, campaign=campaign)


@router.post(
    "/{session_id}/finish",
    dependencies=[Depends(require_admin_session)],
)
async def finish_session(
    session_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> InterviewSessionRecord:
    session = repository.get_interview_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return repository.finish_interview_session(session_id, close_reason="scientist_override")

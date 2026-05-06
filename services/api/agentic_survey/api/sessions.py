from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentic_survey.agents.validator import Validator
from agentic_survey.auth import (
    get_admin_session_from_request,
    get_participant_session_from_request,
    require_admin_session,
)
from agentic_survey.api.background_tasks import (
    cancel_pre_plan_bg,
    spawn_post_turn_bg,
)
from agentic_survey.config import Settings, get_settings
from agentic_survey.engine.event_bus import (
    EventEnvelope,
    get_event_bus,
)
from agentic_survey.engine.interview_loop import (
    opening_turn_message,
    run_interview_turn,
)

# Events kept in the per-campaign ring buffer that operator and participant
# SSE clients subscribe to. ``token`` events are the chunk-by-chunk stream of
# Brain A's reply; bus subscribers never want them (noise, and the HTTP
# response already carries the full reply), so we filter them out at the
# publish boundary. The background task publishes its events directly — the
# names still live here so that future code paths that re-route through the
# filter do not silently drop them.
_BUS_EVENT_NAMES = {
    "turn_start",
    "turn_complete",
    "graph_delta",
    "get_user_input",
    "session_paused",
    "session_finished",
    "validator_scored",
    "brain_b_planned",
    "concepts_extracted",
}
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

_KEEPALIVE_SECONDS = 15.0


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
        content=opening_turn_message(campaign, session),
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
    cancel_pre_plan_bg(session_id=session.id, repository=repository)

    result = await run_interview_turn(
        session_id=session.id,
        participant_content=payload.content,
        chip_selected=payload.chip_selected,
        repository=repository,
        validator=_validator,
        router=get_litellm_router(),
        cache=_retrieval_cache,
    )

    bus_events = [event for event in result.events if event.name in _BUS_EVENT_NAMES]
    get_event_bus().publish_many(campaign.id, bus_events)

    agent_turn = result.agent_turn
    participant_turn = result.participant_turn
    if (
        agent_turn is not None
        and participant_turn is not None
        and result.session.status == "active"
    ):
        spawn_post_turn_bg(
            session_id=result.session.id,
            campaign_id=campaign.id,
            participant_turn_id=participant_turn.id,
            agent_turn_id=agent_turn.id,
            repository=repository,
            router=get_litellm_router(),
            validator=_validator,
            cache=_retrieval_cache,
            bus=get_event_bus(),
        )

    return SessionBundleResponse(session=result.session, campaign=campaign)


@router.get("/{session_id}/stream")
async def stream_session_events(
    session_id: str,
    request: Request,
    since: int | None = Query(default=None, ge=-1),
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> StreamingResponse:
    """Participant-or-admin SSE feed of one session's events.

    Shares the campaign bus with ``/api/campaigns/{id}/stream`` but
    filters envelopes whose ``data.session_id`` does not match. Replay
    follows the ``since`` query param or the standard ``Last-Event-ID``
    header; keepalive comments fire every 15s.
    """
    session = _require_session_access(request, session_id, settings, repository)
    cursor = since
    if cursor is None:
        last_event_id = request.headers.get("last-event-id")
        if last_event_id is not None:
            try:
                cursor = int(last_event_id)
            except ValueError:
                cursor = None
    if cursor is None:
        cursor = -1

    return StreamingResponse(
        _session_event_stream(
            campaign_id=session.campaign_id,
            session_id=session_id,
            request=request,
            since=cursor,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_frame(envelope: EventEnvelope) -> bytes:
    """Format one EventEnvelope as a single SSE frame."""
    payload = json.dumps(envelope.data, default=str, sort_keys=True)
    return f"id: {envelope.seq}\nevent: {envelope.name}\ndata: {payload}\n\n".encode("utf-8")


def _event_matches_session(envelope: EventEnvelope, session_id: str) -> bool:
    return envelope.data.get("session_id") == session_id


async def _session_event_stream(
    *,
    campaign_id: str,
    session_id: str,
    request: Request,
    since: int,
) -> AsyncIterator[bytes]:
    bus = get_event_bus()
    queue = bus.subscribe(campaign_id)
    try:
        for envelope in bus.replay(campaign_id, since=since):
            if await request.is_disconnected():
                return
            if not _event_matches_session(envelope, session_id):
                continue
            yield _sse_frame(envelope)
        while True:
            if await request.is_disconnected():
                return
            try:
                envelope = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            if not _event_matches_session(envelope, session_id):
                continue
            yield _sse_frame(envelope)
    finally:
        bus.unsubscribe(campaign_id, queue)


@router.post("/{session_id}/finish")
async def finish_session(
    session_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> InterviewSessionRecord:
    """Close a session as either the participant or the scientist.

    Participant tokens close their own session (``close_reason='participant_self_close'``)
    so the chat page's "End conversation" affordance has a backend path that
    does not require admin login. Admin tokens still close as
    ``scientist_override``. Anonymous callers get 401 via
    ``_require_session_access``.
    """
    session = _require_session_access(request, session_id, settings, repository)
    participant = get_participant_session_from_request(request, settings, repository)
    is_participant = participant is not None and participant.id == session.id
    close_reason = "participant_self_close" if is_participant else "scientist_override"
    return repository.finish_interview_session(session_id, close_reason=close_reason)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agentic_survey.agents.interviewer import Interviewer, normalize_control_signal
from agentic_survey.agents.validator import Validator
from agentic_survey.auth import (
    get_admin_session_from_request,
    get_participant_session_from_request,
    require_admin_session,
)
from agentic_survey.config import Settings, get_settings
from agentic_survey.engine.session_policy import derive_objective_tags, summarize_session_signals
from agentic_survey.llm.client import get_llm_client
from agentic_survey.repository import (
    Campaign,
    InMemoryRepository,
    InterviewSessionRecord,
    get_repository,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


_llm_client = get_llm_client()
_interviewer = Interviewer(llm=_llm_client)
_validator = Validator(llm=_llm_client)


class ParticipantTurnRequest(BaseModel):
    content: str = Field(min_length=1)


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

    opening = _interviewer.opening_turn(campaign)
    repository.append_interview_turn(
        session.id,
        role="agent",
        content=opening.reply,
        brain_b_intent=opening.brain_b_intent,
        get_user_input=opening.get_user_input,
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
    participant_content = payload.content.strip()
    control_signal = normalize_control_signal(participant_content)

    if control_signal in {"pause", "skip", "continue", "stop"}:
        validation_payload = {
            "control_signal": control_signal,
            "objective_tags": [],
        }
    else:
        last_agent = next(
            (turn.content for turn in reversed(session.turns) if turn.role == "agent"),
            "",
        )
        validation = await _validator.validate(
            campaign=campaign,
            content=participant_content,
            outline=campaign.outline,
            previous_agent_question=last_agent,
        )
        validation_payload = validation.to_dict()
        validation_payload["objective_tags"] = derive_objective_tags(
            content=participant_content,
            outline=campaign.outline,
            validation=validation_payload,
        )

    repository.append_interview_turn(
        session.id,
        role="participant",
        content=participant_content,
        validation=validation_payload,
    )

    refreshed = repository.get_interview_session(session.id)
    assert refreshed is not None

    if control_signal == "pause":
        refreshed = repository.pause_interview_session(refreshed.id, reason="participant_paused")
        return SessionBundleResponse(session=refreshed, campaign=campaign)

    participant_validations = [turn.validation for turn in refreshed.turns if turn.role == "participant"]
    signals = summarize_session_signals(refreshed, campaign.outline, participant_validations)

    if control_signal == "stop":
        closing = await _interviewer.closing_message(
            campaign=campaign,
            session=refreshed,
            outline=campaign.outline,
            close_reason="participant_stop",
        )
        repository.append_interview_turn(
            refreshed.id,
            role="agent",
            content=closing,
            brain_b_intent=None,
            validation={
                "closing": True,
                "close_reason": "participant_stop",
                "participant_turn_count": signals.participant_turn_count,
                "mean_recent_coverage": round(signals.mean_recent_coverage, 3),
                "low_coverage_streak": signals.low_coverage_streak,
                "objective_hits": signals.objective_hits,
            },
        )
        repository.finish_interview_session(refreshed.id, close_reason="participant_stop")
        refreshed = repository.get_interview_session(refreshed.id)
        assert refreshed is not None
        return SessionBundleResponse(session=refreshed, campaign=campaign)

    plan = await _interviewer.next_turn(
        campaign=campaign,
        outline=campaign.outline,
        session=refreshed,
        session_signals=signals,
    )

    if plan.brain_b_intent is not None and plan.brain_b_intent.should_close:
        close_reason = plan.brain_b_intent.close_reason or "brain_b_close"
        closing = await _interviewer.closing_message(
            campaign=campaign,
            session=refreshed,
            outline=campaign.outline,
            close_reason=close_reason,
        )
        repository.append_interview_turn(
            refreshed.id,
            role="agent",
            content=closing,
            brain_b_intent=plan.brain_b_intent,
            validation={
                "closing": True,
                "close_reason": close_reason,
                "participant_turn_count": signals.participant_turn_count,
                "mean_recent_coverage": round(signals.mean_recent_coverage, 3),
                "low_coverage_streak": signals.low_coverage_streak,
                "objective_hits": signals.objective_hits,
            },
        )
        repository.finish_interview_session(refreshed.id, close_reason=close_reason)
    else:
        repository.append_interview_turn(
            refreshed.id,
            role="agent",
            content=plan.reply,
            brain_b_intent=plan.brain_b_intent,
            get_user_input=plan.get_user_input,
        )

    refreshed = repository.get_interview_session(refreshed.id)
    assert refreshed is not None
    return SessionBundleResponse(session=refreshed, campaign=campaign)


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

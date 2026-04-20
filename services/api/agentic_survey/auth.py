from fastapi import Depends, HTTPException, Request, Response

from agentic_survey.config import Settings, get_settings
from agentic_survey.repository import (
    AdminSession,
    InMemoryRepository,
    InterviewSessionRecord,
    get_repository,
)


def set_admin_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        max_age=settings.admin_session_ttl_hours * 60 * 60,
    )


def clear_admin_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(key=settings.admin_session_cookie_name, httponly=True, samesite="lax")


def get_admin_session_from_request(
    request: Request,
    settings: Settings,
    repository: InMemoryRepository,
) -> AdminSession | None:
    token = request.cookies.get(settings.admin_session_cookie_name)
    if not token:
        return None
    return repository.get_admin_session(token)


def require_admin_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> AdminSession:
    session = get_admin_session_from_request(request, settings, repository)
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return session


def set_participant_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.participant_session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        max_age=settings.participant_session_ttl_hours * 60 * 60,
    )


def clear_participant_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.participant_session_cookie_name,
        httponly=True,
        samesite="lax",
    )


def get_participant_session_from_request(
    request: Request,
    settings: Settings,
    repository: InMemoryRepository,
) -> InterviewSessionRecord | None:
    token = request.cookies.get(settings.participant_session_cookie_name)
    if not token:
        return None
    return repository.get_interview_session_by_participant_token(token)


def require_participant_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    repository: InMemoryRepository = Depends(get_repository),
) -> InterviewSessionRecord:
    session = get_participant_session_from_request(request, settings, repository)
    if session is None:
        raise HTTPException(status_code=401, detail="Participant session required")
    return session

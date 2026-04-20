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

router = APIRouter(prefix="/admin", tags=["admin"])


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

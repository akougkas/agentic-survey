from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from agentic_survey.auth import (
    require_admin_session,
    set_participant_session_cookie,
)
from agentic_survey.config import Settings, get_settings
from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.llm.client import get_endpoint_pool
from agentic_survey.repository import (
    Campaign,
    InMemoryRepository,
    InterviewSessionRecord,
    Invite,
    get_repository,
)

router = APIRouter(prefix="/invites", tags=["invites"])


REDEEMABLE_STATES: set[CampaignState] = {
    CampaignState.LIVE,
    CampaignState.MONITORING,
}

CREATABLE_STATES: set[CampaignState] = {
    CampaignState.REVIEWING,
    CampaignState.LIVE,
    CampaignState.MONITORING,
}


class CreateInviteRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    label: str = ""


class InviteInfoResponse(BaseModel):
    invite_id: str
    campaign_id: str
    campaign_title: str
    consent_language: str
    micro_form_schema: list[dict]
    status: str


class RedeemInviteRequest(BaseModel):
    consent_mode: str = Field(pattern="^(anonymous|named)$")
    identity_label: str = ""


class RedeemInviteResponse(BaseModel):
    session: InterviewSessionRecord
    campaign_title: str


@router.post(
    "",
    dependencies=[Depends(require_admin_session)],
)
async def create_invite(
    payload: CreateInviteRequest,
    repository: InMemoryRepository = Depends(get_repository),
) -> Invite:
    campaign = _load_campaign(repository, payload.campaign_id)
    if campaign.state not in CREATABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot create invites while campaign is {campaign.state}",
        )
    return repository.create_invite(campaign.id, label=payload.label.strip())


@router.get(
    "",
    dependencies=[Depends(require_admin_session)],
)
async def list_invites(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> dict[str, list[Invite]]:
    _load_campaign(repository, campaign_id)
    return {"items": repository.list_invites(campaign_id)}


@router.post(
    "/{invite_id}/revoke",
    dependencies=[Depends(require_admin_session)],
)
async def revoke_invite(
    invite_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> Invite:
    invite = repository.get_invite(invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "active":
        raise HTTPException(status_code=409, detail=f"Invite cannot be revoked from status={invite.status}")
    revoked = repository.revoke_invite(invite_id)
    if revoked is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return revoked


@router.get("/{token}")
async def get_invite_info(
    token: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> InviteInfoResponse:
    invite = repository.get_invite_by_token(token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    campaign = _load_campaign(repository, invite.campaign_id)
    return InviteInfoResponse(
        invite_id=invite.id,
        campaign_id=campaign.id,
        campaign_title=campaign.title,
        consent_language=campaign.outline.consent_language,
        micro_form_schema=[field.model_dump() for field in campaign.outline.micro_form_schema],
        status=invite.status,
    )


@router.post("/{token}/redeem")
async def redeem_invite(
    token: str,
    payload: RedeemInviteRequest,
    response: Response,
    repository: InMemoryRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> RedeemInviteResponse:
    invite = repository.get_invite_by_token(token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "active":
        raise HTTPException(status_code=409, detail="Invite has already been used")
    campaign = _load_campaign(repository, invite.campaign_id)
    if campaign.state not in REDEEMABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Campaign is not accepting participants (state={campaign.state})",
        )

    session = repository.start_interview_session(
        campaign_id=campaign.id,
        invite_id=invite.id,
        consent_mode=payload.consent_mode,  # type: ignore[arg-type]
        identity_label=payload.identity_label,
        persona_snapshot=dict(campaign.outline.persona_hints),
        pinned_endpoint=settings.default_interviewer_endpoint,
    )
    # docs/AGENTS.md promises the Interviewer is pinned for the session's lifetime.
    try:
        get_endpoint_pool().pin_session(session.id, settings.default_interviewer_endpoint)
    except KeyError:
        pass
    repository.mark_invite_used(invite.id, session.id)
    set_participant_session_cookie(response, session.participant_token, settings)

    return RedeemInviteResponse(session=session, campaign_title=campaign.title)


def _load_campaign(repository: InMemoryRepository, campaign_id: str) -> Campaign:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

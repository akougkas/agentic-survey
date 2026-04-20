from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from agentic_survey.agents.designer import CampaignDesigner
from agentic_survey.bundles import (
    ProductBundleManifest,
    list_campaign_seeds,
    load_bundle_manifest,
    load_campaign_seed,
    materialize_outline,
)
from agentic_survey.auth import require_admin_session
from agentic_survey.engine.state_machine import ALLOWED_TRANSITIONS, CampaignState, StateTransitionError
from agentic_survey.llm.catalog import AgentRole as CatalogRole, CatalogEntry
from agentic_survey.llm.client import get_llm_client
from agentic_survey.repository import (
    Campaign,
    DesignerSession,
    InMemoryRepository,
    InterviewSessionRecord,
    Invite,
    OutlineRevision,
    get_repository,
)

public_router = APIRouter(prefix="/campaigns", tags=["campaigns"])
router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_admin_session)],
)
designer = CampaignDesigner(llm=get_llm_client())


class CreateCampaignRequest(BaseModel):
    title: str = Field(min_length=1)
    min_n: int = Field(default=12, ge=1)
    max_n: int = Field(default=40, ge=1)
    agent_models: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "CreateCampaignRequest":
        if self.max_n < self.min_n:
            raise ValueError("max_n must be greater than or equal to min_n")
        return self


class DesignerTurnRequest(BaseModel):
    content: str = Field(min_length=1)


class CampaignSeedSummary(BaseModel):
    slug: str
    title: str
    description: str
    min_n: int
    max_n: int


class BundleCatalogResponse(BaseModel):
    bundle: ProductBundleManifest
    seeds: list[CampaignSeedSummary]


class CampaignBundleResponse(BaseModel):
    campaign: Campaign
    designer_session: DesignerSession | None = None
    invites: list[Invite] = Field(default_factory=list)
    sessions: list[InterviewSessionRecord] = Field(default_factory=list)
    metrics: "CampaignMetrics"
    readiness: "OutlineReadiness"
    next_states: list[CampaignState] = Field(default_factory=list)
    outline_revisions: list[OutlineRevision] = Field(default_factory=list)


class OutlineReadinessCheck(BaseModel):
    key: str
    label: str
    ready: bool
    detail: str


class OutlineReadiness(BaseModel):
    ready_for_review: bool
    completed: int
    total: int
    checks: list[OutlineReadinessCheck]


class CampaignMetrics(BaseModel):
    invite_count: int = 0
    active_invite_count: int = 0
    used_invite_count: int = 0
    revoked_invite_count: int = 0
    session_count: int = 0
    active_session_count: int = 0
    finished_session_count: int = 0


class CampaignOverviewItem(BaseModel):
    campaign: Campaign
    designer_session: DesignerSession | None = None
    metrics: CampaignMetrics
    readiness: OutlineReadiness
    next_states: list[CampaignState] = Field(default_factory=list)
    latest_outline_revision: OutlineRevision | None = None


class CampaignOverviewSummary(BaseModel):
    total_campaigns: int
    seeded_campaign_count: int
    review_ready_count: int
    live_campaign_count: int
    active_session_count: int


class CampaignOverviewResponse(BaseModel):
    bundle: ProductBundleManifest
    seeds: list[CampaignSeedSummary]
    summary: CampaignOverviewSummary
    items: list[CampaignOverviewItem]


class AdvanceCampaignRequest(BaseModel):
    target_state: CampaignState


class CreateSeededCampaignRequest(BaseModel):
    seed_slug: str = Field(min_length=1)


def _bundle_catalog() -> BundleCatalogResponse:
    manifest = load_bundle_manifest()
    seeds = list_campaign_seeds()
    return BundleCatalogResponse(
        bundle=manifest,
        seeds=[
            CampaignSeedSummary(
                slug=seed.slug,
                title=seed.title,
                description=seed.description,
                min_n=seed.min_n,
                max_n=seed.max_n,
            )
            for seed in seeds
        ],
    )


def _campaign_metrics(repository: InMemoryRepository, campaign_id: str) -> CampaignMetrics:
    invites = repository.list_invites(campaign_id)
    sessions = repository.list_interview_sessions(campaign_id)
    return CampaignMetrics(
        invite_count=len(invites),
        active_invite_count=sum(1 for invite in invites if invite.status == "active"),
        used_invite_count=sum(1 for invite in invites if invite.status == "used"),
        revoked_invite_count=sum(1 for invite in invites if invite.status == "revoked"),
        session_count=len(sessions),
        active_session_count=sum(1 for session in sessions if session.status == "active"),
        finished_session_count=sum(1 for session in sessions if session.status == "finished"),
    )


def _outline_readiness(campaign: Campaign, session: DesignerSession | None) -> OutlineReadiness:
    scientist_turn_count = len([turn for turn in session.turns if turn.role == "scientist"]) if session else 0
    seed_backed = campaign.source == "seed"
    checks = [
        OutlineReadinessCheck(
            key="summary",
            label="Study summary",
            ready=bool(campaign.outline.scientist_summary.strip()),
            detail=(
                "Summary supplied by the bundle seed."
                if seed_backed
                else ("Brief summary captured." if campaign.outline.scientist_summary.strip() else "Capture the campaign brief in one or two sentences.")
            ),
        ),
        OutlineReadinessCheck(
            key="objectives",
            label="Objectives",
            ready=len(campaign.outline.objectives) >= 2,
            detail=f"{len(campaign.outline.objectives)} objective(s) captured.",
        ),
        OutlineReadinessCheck(
            key="probes",
            label="Interview probes",
            ready=len(campaign.outline.probes) >= 3,
            detail=f"{len(campaign.outline.probes)} probe(s) captured.",
        ),
        OutlineReadinessCheck(
            key="freshness_query",
            label="Freshness query",
            ready=bool(campaign.outline.freshness_query.strip()),
            detail=(
                f"Query: {campaign.outline.freshness_query}"
                if campaign.outline.freshness_query.strip()
                else "Add the grounding query the runtime should use for design-time freshness."
            ),
        ),
        OutlineReadinessCheck(
            key="design_turns",
            label="Design turns",
            ready=seed_backed or scientist_turn_count >= 4,
            detail=(
                "Seed-backed campaign is already reviewable."
                if seed_backed
                else f"{scientist_turn_count}/4 operator turns captured."
            ),
        ),
    ]
    completed = sum(1 for check in checks if check.ready)
    return OutlineReadiness(
        ready_for_review=campaign.outline_status == "ready_for_review",
        completed=completed,
        total=len(checks),
        checks=checks,
    )


def _next_states(campaign: Campaign) -> list[CampaignState]:
    next_states = list(ALLOWED_TRANSITIONS[campaign.state])
    if campaign.state == CampaignState.DESIGNING and campaign.outline_status != "ready_for_review":
        return []
    return next_states


def _build_campaign_bundle(
    campaign_id: str,
    repository: InMemoryRepository,
) -> CampaignBundleResponse:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    designer_session = repository.get_designer_session(campaign_id)
    return CampaignBundleResponse(
        campaign=campaign,
        designer_session=designer_session,
        invites=repository.list_invites(campaign_id),
        sessions=repository.list_interview_sessions(campaign_id),
        metrics=_campaign_metrics(repository, campaign_id),
        readiness=_outline_readiness(campaign, designer_session),
        next_states=_next_states(campaign),
        outline_revisions=repository.list_outline_revisions(campaign_id),
    )


@router.get("")
async def list_campaigns(
    repository: InMemoryRepository = Depends(get_repository),
) -> dict[str, list[Campaign]]:
    return {"items": repository.list_campaigns()}


@router.get("/overview")
async def get_campaign_overview(
    repository: InMemoryRepository = Depends(get_repository),
) -> CampaignOverviewResponse:
    catalog = _bundle_catalog()
    campaigns = repository.list_campaigns()
    items = []
    for campaign in campaigns:
        designer_session = repository.get_designer_session(campaign.id)
        revisions = repository.list_outline_revisions(campaign.id)
        items.append(
            CampaignOverviewItem(
                campaign=campaign,
                designer_session=designer_session,
                metrics=_campaign_metrics(repository, campaign.id),
                readiness=_outline_readiness(campaign, designer_session),
                next_states=_next_states(campaign),
                latest_outline_revision=revisions[-1] if revisions else None,
            )
        )
    return CampaignOverviewResponse(
        bundle=catalog.bundle,
        seeds=catalog.seeds,
        summary=CampaignOverviewSummary(
            total_campaigns=len(campaigns),
            seeded_campaign_count=sum(1 for campaign in campaigns if campaign.source == "seed"),
            review_ready_count=sum(1 for campaign in campaigns if campaign.outline_status == "ready_for_review"),
            live_campaign_count=sum(1 for campaign in campaigns if campaign.state == CampaignState.LIVE),
            active_session_count=sum(item.metrics.active_session_count for item in items),
        ),
        items=items,
    )


@router.get("/catalog")
async def get_bundle_catalog() -> BundleCatalogResponse:
    return _bundle_catalog()


@public_router.get("/model-catalog")
async def get_model_catalog(
    role: CatalogRole | None = None,
    repository: InMemoryRepository = Depends(get_repository),
) -> list[CatalogEntry]:
    return [entry for entry in repository.list_catalog(role) if entry.enabled]


@router.post("")
async def create_campaign(
    payload: CreateCampaignRequest,
    repository: InMemoryRepository = Depends(get_repository),
) -> Campaign:
    try:
        return repository.create_campaign(
            title=payload.title.strip(),
            min_n=payload.min_n,
            max_n=payload.max_n,
            agent_models=payload.agent_models,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/from-seed")
async def create_campaign_from_seed(
    payload: CreateSeededCampaignRequest,
    repository: InMemoryRepository = Depends(get_repository),
) -> Campaign:
    seed = load_campaign_seed(payload.seed_slug.strip())
    outline = materialize_outline(seed)
    return repository.create_campaign(
        title=seed.title,
        min_n=seed.min_n,
        max_n=seed.max_n,
        outline=outline,
        source="seed",
        state=CampaignState.REVIEWING,
        outline_status="ready_for_review",
    )


@router.patch("/{campaign_id}/models")
async def update_campaign_models(
    campaign_id: str,
    payload: dict[str, str | None],
    repository: InMemoryRepository = Depends(get_repository),
) -> Campaign:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        return repository.update_campaign_models(campaign_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> CampaignBundleResponse:
    return _build_campaign_bundle(campaign_id, repository)


@router.post("/{campaign_id}/advance")
async def advance_campaign(
    campaign_id: str,
    payload: AdvanceCampaignRequest,
    repository: InMemoryRepository = Depends(get_repository),
) -> CampaignBundleResponse:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if payload.target_state == CampaignState.REVIEWING and campaign.outline_status != "ready_for_review":
        raise HTTPException(
            status_code=409,
            detail="Outline is still collecting the brief; finish the designer loop first.",
        )
    try:
        repository.advance_campaign(campaign_id, payload.target_state)
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _build_campaign_bundle(campaign_id, repository)


@router.get("/{campaign_id}/sessions")
async def list_campaign_sessions(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> dict[str, list[InterviewSessionRecord]]:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"items": repository.list_interview_sessions(campaign_id)}


@router.post("/{campaign_id}/designer/start")
async def start_designer(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> CampaignBundleResponse:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    session = repository.start_designer_session(
        campaign_id=campaign_id,
        opening_message=designer.opening_message(campaign),
    )
    bundle = _build_campaign_bundle(campaign_id, repository)
    bundle.designer_session = session
    return bundle


@router.post("/{campaign_id}/designer/turns")
async def submit_designer_turn(
    campaign_id: str,
    payload: DesignerTurnRequest,
    repository: InMemoryRepository = Depends(get_repository),
) -> CampaignBundleResponse:
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    session = repository.get_designer_session(campaign_id)
    if session is None:
        raise HTTPException(status_code=409, detail="Designer session has not started")

    repository.append_designer_turn(campaign_id, "scientist", payload.content.strip())
    session = repository.get_designer_session(campaign_id)
    if session is None:
        raise HTTPException(status_code=409, detail="Designer session has not started")

    outline = await designer.build_outline(campaign, session)
    repository.update_outline(
        campaign_id,
        outline,
        ready_for_review=designer.is_ready_for_review(session, outline),
    )

    reply = await designer.next_reply(campaign, session, outline)
    repository.append_designer_turn(campaign_id, "designer", reply)

    campaign = repository.get_campaign(campaign_id)
    session = repository.get_designer_session(campaign_id)
    if campaign is None or session is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    bundle = _build_campaign_bundle(campaign_id, repository)
    bundle.designer_session = session
    return bundle

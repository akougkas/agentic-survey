from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from agentic_survey.bundles import BundleBranding, BundleCopy, load_bundle_manifest, resolve_bundle_dir, resolve_public_base_url
from agentic_survey.config import Settings, get_settings

router = APIRouter(prefix="/system", tags=["system"])


class RuntimeContextResponse(BaseModel):
    app_name: str
    runtime_name: str = "Agentic Survey"
    bundle_dir: str
    bundle_slug: str
    bundle_name: str
    public_base_url: str
    declared_public_base_url: str | None = None
    branding: BundleBranding
    ui: BundleCopy
    campaign_seed_count: int


@router.get("/context")
async def get_runtime_context(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RuntimeContextResponse:
    manifest = load_bundle_manifest()
    app_name = manifest.name if settings.app_name == "Agentic Survey" else settings.app_name
    public_base_url = resolve_public_base_url(
        manifest,
        forwarded_public_base_url=request.headers.get("x-survey-public-base-url", ""),
        configured_public_base_url=settings.public_base_url,
        frontend_origin=settings.frontend_origin,
        request_base_url=str(request.base_url),
    )
    return RuntimeContextResponse(
        app_name=app_name,
        bundle_dir=str(resolve_bundle_dir()),
        bundle_slug=manifest.slug,
        bundle_name=manifest.name,
        public_base_url=public_base_url,
        declared_public_base_url=manifest.public_base_url or None,
        branding=manifest.branding,
        ui=manifest.ui,
        campaign_seed_count=len(manifest.campaigns),
    )

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentic_survey.api.admin import router as admin_router
from agentic_survey.api.campaigns import public_router as public_campaigns_router, router as campaigns_router
from agentic_survey.api.invites import router as invites_router
from agentic_survey.api.knowledge import router as knowledge_router
from agentic_survey.api.models import router as models_router
from agentic_survey.api.sessions import router as sessions_router
from agentic_survey.api.system import router as system_router
from agentic_survey.api.turns import router as turns_router
from agentic_survey.bundles import load_bundle_manifest
from agentic_survey.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app_title = settings.app_name
    if app_title == "Agentic Survey":
        try:
            app_title = load_bundle_manifest().name
        except (FileNotFoundError, ValueError):
            app_title = settings.app_name
    app = FastAPI(title=app_title)
    api_router = APIRouter(prefix="/api")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api_router.get("/healthz", tags=["system"])
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    api_router.include_router(system_router)
    api_router.include_router(public_campaigns_router)
    api_router.include_router(admin_router)
    api_router.include_router(models_router)
    api_router.include_router(campaigns_router)
    api_router.include_router(invites_router)
    api_router.include_router(knowledge_router)
    api_router.include_router(sessions_router)
    api_router.include_router(turns_router)
    app.include_router(api_router)
    return app


app = create_app()

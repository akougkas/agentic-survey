from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agentic_survey.auth import require_admin_session

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_admin_session)],
)


class KnowledgeIngestRequest(BaseModel):
    campaign_id: str
    source: str
    content: str


@router.post("/ingest")
async def ingest_knowledge(payload: KnowledgeIngestRequest) -> dict[str, str]:
    return {
        "id": "knowledge:pending",
        "campaign_id": payload.campaign_id,
        "source": payload.source,
    }

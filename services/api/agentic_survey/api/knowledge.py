from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agentic_survey.auth import require_admin_session
from agentic_survey.repository import (
    InMemoryRepository,
    KnowledgeSource,
    get_repository,
)

router = APIRouter(
    prefix="/admin/campaigns",
    tags=["knowledge"],
    dependencies=[Depends(require_admin_session)],
)


class KnowledgeSourceSummary(BaseModel):
    source: KnowledgeSource
    chunk_count: int


class KnowledgeListResponse(BaseModel):
    campaign_id: str
    by_status: dict[str, list[KnowledgeSourceSummary]] = Field(default_factory=dict)
    total: int = 0


class ApprovalResponse(BaseModel):
    source: KnowledgeSource
    chunk_count: int


class BulkApprovalResponse(BaseModel):
    approved_source_ids: list[str]
    approved_chunk_count: int


@router.get("/{campaign_id}/knowledge")
async def list_knowledge(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> KnowledgeListResponse:
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sources = repository.list_knowledge_sources(campaign_id)
    by_status: dict[str, list[KnowledgeSourceSummary]] = {}
    for source in sources:
        summary = KnowledgeSourceSummary(
            source=source,
            chunk_count=repository.count_chunks_for_source(source.id),
        )
        by_status.setdefault(source.status, []).append(summary)
    return KnowledgeListResponse(
        campaign_id=campaign_id,
        by_status=by_status,
        total=len(sources),
    )


@router.post("/{campaign_id}/knowledge/{source_id}/approve")
async def approve_knowledge_source(
    campaign_id: str,
    source_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> ApprovalResponse:
    source = repository.get_knowledge_source(source_id)
    if source is None or source.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    updated = repository.update_knowledge_source_status(
        source_id,
        status="approved",
        approved_by="scientist",
    )
    return ApprovalResponse(
        source=updated,
        chunk_count=repository.count_chunks_for_source(source_id),
    )


@router.post("/{campaign_id}/knowledge/{source_id}/reject")
async def reject_knowledge_source(
    campaign_id: str,
    source_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> ApprovalResponse:
    source = repository.get_knowledge_source(source_id)
    if source is None or source.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    updated = repository.update_knowledge_source_status(source_id, status="rejected")
    return ApprovalResponse(
        source=updated,
        chunk_count=repository.count_chunks_for_source(source_id),
    )


@router.post("/{campaign_id}/knowledge/approve-all-seeds")
async def approve_all_seeds(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> BulkApprovalResponse:
    """Demo convenience: bulk-approve every pending bundle_seed for this campaign.

    Not a substitute for the per-source approval workflow. Use when the
    scientist has already blessed the mounted bundle and wants to skip the
    per-card click-through during a demo. Sources in states other than
    ``pending_approval`` are left alone.
    """
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    approved_ids: list[str] = []
    chunk_count = 0
    for source in repository.list_knowledge_sources(campaign_id):
        if source.kind != "bundle_seed" or source.status != "pending_approval":
            continue
        repository.update_knowledge_source_status(
            source.id,
            status="approved",
            approved_by="bulk_approve_seeds",
        )
        approved_ids.append(source.id)
        chunk_count += repository.count_chunks_for_source(source.id)
    return BulkApprovalResponse(
        approved_source_ids=approved_ids,
        approved_chunk_count=chunk_count,
    )

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from agentic_survey.auth import require_admin_session
from agentic_survey.llm.catalog import AgentRole, CatalogEntry, Endpoint
from agentic_survey.repository import InMemoryRepository, get_repository

router = APIRouter(
    prefix="/admin/models",
    tags=["admin-models"],
    dependencies=[Depends(require_admin_session)],
)


class CatalogEntryPayload(BaseModel):
    catalog_id: str = Field(min_length=1)
    role: AgentRole
    endpoint: Endpoint
    model_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    notes: str | None = None
    enabled: bool = True
    is_default: bool = False


class CatalogEntryPatch(BaseModel):
    endpoint: Endpoint | None = None
    model_id: str | None = Field(default=None, min_length=1)
    label: str | None = Field(default=None, min_length=1)
    notes: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


@router.get("")
async def list_catalog(
    role: AgentRole | None = None,
    repository: InMemoryRepository = Depends(get_repository),
) -> list[CatalogEntry]:
    return repository.list_catalog(role)


@router.post("")
async def create_entry(
    payload: CatalogEntryPayload,
    repository: InMemoryRepository = Depends(get_repository),
) -> CatalogEntry:
    try:
        return repository.create_catalog_entry(CatalogEntry(**payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{catalog_id}/{role}")
async def update_entry(
    catalog_id: str,
    role: AgentRole,
    payload: CatalogEntryPatch,
    repository: InMemoryRepository = Depends(get_repository),
) -> CatalogEntry:
    patch = payload.model_dump(exclude_unset=True)
    try:
        return repository.update_catalog_entry(catalog_id, role, patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{catalog_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    catalog_id: str,
    role: AgentRole,
    repository: InMemoryRepository = Depends(get_repository),
) -> Response:
    try:
        repository.delete_catalog_entry(catalog_id, role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

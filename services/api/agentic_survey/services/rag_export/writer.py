"""Write the ``./campaigns/{slug}/rag/`` audit artifact.

Every call is idempotent: the rag folder is rebuilt from scratch from
SurrealDB reads, so re-syncs never leave stale files behind. The writer
records a ``campaign_export`` row per run so the admin drawer can show
"last synced at" without crawling disk.

Invariants preserved here:

- SurrealDB is truth. The writer never reads from disk, only writes.
- No embedding calls, no web calls. Pure SurrealDB → JSON.
- No silent errors. A missing campaign raises; partial writes surface
  through the exception and the next sync overwrites.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentic_survey.config import get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "slugify_campaign_title",
    "sync_campaign_rag_folder",
]


_SLUG_WHITESPACE = re.compile(r"\s+")
_SLUG_DISALLOWED = re.compile(r"[^a-z0-9-]+")
_SLUG_DASHES = re.compile(r"-+")


def slugify_campaign_title(title: str) -> str:
    """Lowercase, whitespace-collapsed, ``[a-z0-9-]``-only slug.

    Returns an empty string for titles that contain no latin alphanumerics
    after normalization; callers append a disambiguator (short campaign
    id) in that case.
    """
    lowered = (title or "").strip().lower()
    dashed = _SLUG_WHITESPACE.sub("-", lowered)
    cleaned = _SLUG_DISALLOWED.sub("", dashed)
    collapsed = _SLUG_DASHES.sub("-", cleaned).strip("-")
    return collapsed


def _short_campaign_id(campaign_id: str) -> str:
    # "campaign-1f62c87bf9dc" → "1f62c87b"
    tail = campaign_id.split("-", 1)[-1]
    return tail[:8] or campaign_id


def _resolve_slug(repository: Any, campaign: Any) -> str:
    base = slugify_campaign_title(campaign.title)
    short_id = _short_campaign_id(campaign.id)
    if not base:
        return short_id
    siblings = [
        candidate
        for candidate in repository.list_campaigns()
        if slugify_campaign_title(candidate.title) == base
    ]
    if not siblings:
        return base
    siblings.sort(key=lambda c: (c.created_at, c.id))
    if siblings[0].id == campaign.id:
        return base
    return f"{base}-{short_id}"


@dataclass(slots=True)
class _WrittenFile:
    path: Path
    lines: int
    bytes: int


def _write_jsonl(path: Path, rows: list[dict]) -> _WrittenFile:
    text_lines: list[str] = []
    for row in rows:
        text_lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    # Produce one trailing newline only when there is content; an empty
    # file is ``b""`` so ``wc -l`` stays honest.
    payload = ("\n".join(text_lines) + "\n") if text_lines else ""
    path.write_text(payload, encoding="utf-8")
    return _WrittenFile(path=path, lines=len(text_lines), bytes=path.stat().st_size)


def _write_json(path: Path, payload: dict) -> _WrittenFile:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    line_count = text.count("\n")
    return _WrittenFile(path=path, lines=line_count, bytes=path.stat().st_size)


def _source_row(source: Any) -> dict:
    return {
        "id": source.id,
        "kind": source.kind,
        "title": source.title,
        "url": source.url,
        "status": source.status,
        "hash": source.hash,
        "rationale": source.rationale,
        "approved_at": source.approved_at,
        "approved_by": source.approved_by,
        "error_detail": source.error_detail,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _chunk_row(chunk: Any) -> dict:
    # ``KnowledgeChunk`` does not carry an embedding field; the Surreal
    # row does but it belongs in the vector index, not a grep artifact.
    return {
        "id": chunk.id,
        "source_id": chunk.source_id,
        "position": chunk.position,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "content": chunk.content,
    }


def _audit_row(audit: Any) -> dict:
    return {
        "id": audit.id,
        "surface": audit.surface,
        "query": audit.query,
        "top_k": audit.top_k,
        "mode": audit.mode,
        "cache_hit": audit.cache_hit,
        "chunk_ids": list(audit.chunk_ids),
        "scores": list(audit.scores),
        "created_at": audit.created_at,
    }


def _concept_row(concept: Any) -> dict:
    return {
        "id": concept.id,
        "label": concept.label,
        "type": concept.type,
        "mention_count": concept.mention_count,
        "first_seen": concept.first_seen,
    }


def _edge_row(edge: dict) -> dict:
    return {
        "from": edge["from_id"],
        "to": edge["to_id"],
        "edge_table": edge["edge_table"],
        "kind": edge["kind"],
        "confidence": edge["confidence"],
        "session_id": edge["session_id"],
        "turn_id": edge["turn_id"],
        "created_at": edge["created_at"],
    }


def _write_readme(
    *,
    path: Path,
    campaign: Any,
    slug: str,
    synced_at: str,
    files: list[_WrittenFile],
    rag_dir: Path,
) -> _WrittenFile:
    lines: list[str] = []
    lines.append(f"# RAG export — {campaign.title}")
    lines.append("")
    lines.append(
        f"Campaign `{campaign.id}` synced at `{synced_at}` into `{slug}`. "
        "SurrealDB is the source of truth; this folder is a grep-only "
        "audit mirror and is rebuilt on every sync."
    )
    lines.append("")
    lines.append("| file | lines | bytes |")
    lines.append("| --- | --- | --- |")
    for written in files:
        rel = written.path.relative_to(rag_dir)
        lines.append(f"| `{rel}` | {written.lines} | {written.bytes} |")
    lines.append("")
    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")
    return _WrittenFile(path=path, lines=len(lines), bytes=path.stat().st_size)


async def sync_campaign_rag_folder(
    *,
    campaign_id: str,
    repository: Any,
    root: Path | None = None,
    slug_override: str | None = None,
) -> Path:
    """Rebuild ``./campaigns/{slug}/rag/`` from SurrealDB.

    Each call deletes the prior rag directory for this campaign before
    rewriting it so stale files cannot accumulate. Returns the rag
    directory path so the admin route can echo it back.
    """
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise KeyError(f"campaign {campaign_id} not found")

    base_root = Path(root) if root is not None else Path(get_settings().export_dir)
    slug = slug_override or _resolve_slug(repository, campaign)
    rag_dir = (base_root / slug / "rag").resolve()

    if rag_dir.exists():
        shutil.rmtree(rag_dir)
    rag_dir.mkdir(parents=True, exist_ok=True)

    synced_at = datetime.now(tz=UTC).isoformat()
    written_files: list[_WrittenFile] = []

    # sources.jsonl — all statuses, chronological.
    sources = sorted(
        repository.list_knowledge_sources(campaign_id),
        key=lambda s: (s.created_at, s.id),
    )
    sources_file = _write_jsonl(
        rag_dir / "sources.jsonl", [_source_row(s) for s in sources]
    )
    written_files.append(sources_file)

    # chunks/{source_id}.jsonl — approved chunks only, sorted by position.
    chunks_dir = rag_dir / "chunks"
    chunk_files_written = 0
    chunk_bytes_written = 0
    for source in sources:
        chunks = repository.list_knowledge_chunks_for_source(source.id)
        approved = sorted(
            (chunk for chunk in chunks if chunk.approved),
            key=lambda c: c.position,
        )
        if not approved:
            continue
        chunks_dir.mkdir(parents=True, exist_ok=True)
        written = _write_jsonl(
            chunks_dir / f"{source.id}.jsonl", [_chunk_row(c) for c in approved]
        )
        written_files.append(written)
        chunk_files_written += 1
        chunk_bytes_written += written.bytes

    # queries.jsonl — all retrieval_audits for the campaign, oldest first.
    audits = repository.list_retrieval_audits_for_campaign(campaign_id)
    queries_file = _write_jsonl(
        rag_dir / "queries.jsonl", [_audit_row(a) for a in audits]
    )
    written_files.append(queries_file)

    # graph.json — concepts + merged mentioned_with + contradicts edges.
    concepts = repository.list_concepts_for_campaign(campaign_id)
    edges = repository.list_graph_edges_for_campaign(campaign_id)
    graph_payload = {
        "concepts": [_concept_row(c) for c in concepts],
        "edges": [_edge_row(e) for e in edges],
    }
    graph_file = _write_json(rag_dir / "graph.json", graph_payload)
    written_files.append(graph_file)

    # README.md — regenerated index. Machine-owned; do not hand-edit.
    readme_file = _write_readme(
        path=rag_dir / "README.md",
        campaign=campaign,
        slug=slug,
        synced_at=synced_at,
        files=list(written_files),
        rag_dir=rag_dir,
    )
    written_files.append(readme_file)

    manifest = {
        "synced_at": synced_at,
        "file_counts": {
            "sources": sources_file.lines,
            "chunks": chunk_files_written,
            "queries": queries_file.lines,
            "concepts": len(concepts),
            "edges": len(edges),
        },
        "bytes": {
            "sources": sources_file.bytes,
            "chunks": chunk_bytes_written,
            "queries": queries_file.bytes,
            "graph": graph_file.bytes,
            "readme": readme_file.bytes,
        },
    }
    repository.create_campaign_export(
        campaign_id=campaign_id,
        manifest=manifest,
        export_path=str(rag_dir),
    )

    logger.debug(
        "rag_export.sync campaign=%s slug=%s files=%d",
        campaign_id,
        slug,
        len(written_files),
    )
    return rag_dir

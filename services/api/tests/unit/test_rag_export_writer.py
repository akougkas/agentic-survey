"""RAG export sync rebuilds ``./campaigns/{slug}/rag/`` idempotently.

The writer is the only M6 disk consumer; these tests pin the exact file
layout, content filters, and idempotency behavior so admin-side UI can
depend on them.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from agentic_survey.engine.graph_builder import apply_validator_to_graph
from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.rag_export.writer import sync_campaign_rag_folder


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}


def _approve(repo: InMemoryRepository, source_id: str) -> None:
    repo.update_knowledge_source_status(source_id, status="approved", approved_by="tester")


def _seed_sources_with_chunks(
    repo: InMemoryRepository, campaign_id: str, *, n_sources: int, chunks_per_source: int
) -> list[str]:
    ids: list[str] = []
    for s in range(n_sources):
        source = repo.create_knowledge_source(
            campaign_id=campaign_id,
            kind="raw_text",
            title=f"Source {s}",
            hash_value=f"hash-{s}",
            status="pending_approval",
        )
        # Insert chunks out of position order to prove the writer sorts.
        positions = list(range(chunks_per_source))
        for pos in reversed(positions):
            repo.create_knowledge_chunk(
                campaign_id=campaign_id,
                source_id=source.id,
                content=f"chunk {s}-{pos}",
                position=pos,
                char_start=pos * 10,
                char_end=pos * 10 + 8,
                approved=False,
            )
        _approve(repo, source.id)
        ids.append(source.id)
    return ids


def _run_sync(repo: InMemoryRepository, campaign_id: str, root: Path) -> Path:
    return asyncio.run(
        sync_campaign_rag_folder(
            campaign_id=campaign_id,
            repository=repo,
            root=root,
            slug_override="pinned",
        )
    )


def test_empty_campaign_creates_scaffold_without_chunks_dir(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Empty", min_n=3, max_n=6)

    rag_dir = _run_sync(repo, campaign.id, tmp_path)

    assert (rag_dir / "sources.jsonl").read_text(encoding="utf-8") == ""
    assert (rag_dir / "queries.jsonl").read_text(encoding="utf-8") == ""
    graph = json.loads((rag_dir / "graph.json").read_text(encoding="utf-8"))
    assert graph == {"concepts": [], "edges": []}
    assert (rag_dir / "README.md").is_file()
    assert not (rag_dir / "chunks").exists()


def test_two_sources_produce_sorted_chunk_files(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Chunks", min_n=3, max_n=6)
    source_ids = _seed_sources_with_chunks(
        repo, campaign.id, n_sources=2, chunks_per_source=5
    )

    rag_dir = _run_sync(repo, campaign.id, tmp_path)

    sources_lines = (rag_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(sources_lines) == 2
    rows = [json.loads(line) for line in sources_lines]
    # All statuses are present; approved-only filter is chunks-only.
    assert all(row["status"] == "approved" for row in rows)

    chunks_dir = rag_dir / "chunks"
    assert chunks_dir.is_dir()
    files = sorted(chunks_dir.iterdir())
    assert len(files) == 2
    for source_id in source_ids:
        path = chunks_dir / f"{source_id}.jsonl"
        assert path.is_file()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        positions = [json.loads(line)["position"] for line in lines]
        assert positions == sorted(positions) == [0, 1, 2, 3, 4]
        # No embedding field in the export.
        assert all("embedding" not in json.loads(line) for line in lines)


def test_sources_jsonl_includes_rejected_and_failed_rows(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="All Statuses", min_n=3, max_n=6)
    rejected = repo.create_knowledge_source(
        campaign_id=campaign.id, kind="url", title="Rejected",
        hash_value="h1", url="https://example.com/a", status="pending_approval",
    )
    repo.update_knowledge_source_status(rejected.id, status="rejected")
    failed = repo.create_knowledge_source(
        campaign_id=campaign.id, kind="url", title="Failed",
        hash_value="h2", url="https://example.com/b", status="pending_approval",
    )
    repo.update_knowledge_source_status(failed.id, status="failed", error_detail="boom")

    rag_dir = _run_sync(repo, campaign.id, tmp_path)
    rows = [
        json.loads(line)
        for line in (rag_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["failed", "rejected"]
    assert any(row["error_detail"] == "boom" for row in rows)


def test_unapproved_source_skips_its_chunks_file(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Pending", min_n=3, max_n=6)
    source = repo.create_knowledge_source(
        campaign_id=campaign.id, kind="raw_text", title="Pending",
        hash_value="p1", status="pending_approval",
    )
    repo.create_knowledge_chunk(
        campaign_id=campaign.id, source_id=source.id,
        content="x", position=0, char_start=0, char_end=1, approved=False,
    )

    rag_dir = _run_sync(repo, campaign.id, tmp_path)

    # Source row exists (all statuses) but no chunks file is created
    # because the source was never approved.
    assert (rag_dir / "sources.jsonl").read_text().splitlines()
    assert not (rag_dir / "chunks").exists()


def test_graph_json_mirrors_m5_graph(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Graph", min_n=3, max_n=6)
    validation = {
        "extracted_concepts": [
            {"label": "alpha", "type": "theme"},
            {"label": "beta", "type": "theme"},
            {"label": "gamma", "type": "theme"},
        ],
        "extracted_relations": [
            {"from": "alpha", "to": "beta", "kind": "contradicts", "confidence": 0.7},
        ],
    }
    asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign.id,
            session_id="sess-1",
            turn_id="turn-1",
            validation=validation,
            repository=repo,
            router=_StubRouter(),
        )
    )

    rag_dir = _run_sync(repo, campaign.id, tmp_path)
    graph = json.loads((rag_dir / "graph.json").read_text(encoding="utf-8"))

    assert len(graph["concepts"]) == 3
    for concept in graph["concepts"]:
        assert set(concept.keys()) == {
            "id", "label", "type", "mention_count", "first_seen",
        }
    # C(3,2)=3 co-occurrence edges + 1 contradicts edge = 4.
    assert len(graph["edges"]) == 4
    kinds = {edge["kind"] for edge in graph["edges"]}
    assert "co_occurrence" in kinds and "contradicts" in kinds
    tables = {edge["edge_table"] for edge in graph["edges"]}
    assert tables == {"mentioned_with", "contradicts"}


def test_queries_jsonl_is_chronological(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Audits", min_n=3, max_n=6)
    for i in range(3):
        repo.record_retrieval_audit(
            campaign_id=campaign.id,
            surface="designer",
            query=f"q{i}",
            top_k=5,
            chunk_ids=[],
            scores=[],
            mode="hybrid",
            cache_hit=False,
        )
        time.sleep(0.001)

    rag_dir = _run_sync(repo, campaign.id, tmp_path)
    rows = [
        json.loads(line)
        for line in (rag_dir / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["query"] for row in rows] == ["q0", "q1", "q2"]


def test_resync_overwrites_stale_files(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Idempotent", min_n=3, max_n=6)
    rag_dir = _run_sync(repo, campaign.id, tmp_path)

    synthetic = rag_dir / "synthetic.txt"
    synthetic.write_text("this should disappear", encoding="utf-8")
    assert synthetic.is_file()

    _run_sync(repo, campaign.id, tmp_path)
    assert not synthetic.exists()
    # Canonical files still present.
    assert (rag_dir / "sources.jsonl").is_file()
    assert (rag_dir / "graph.json").is_file()


def test_campaign_export_row_written_each_sync(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Manifest", min_n=3, max_n=6)
    _seed_sources_with_chunks(repo, campaign.id, n_sources=1, chunks_per_source=2)

    _run_sync(repo, campaign.id, tmp_path)
    _run_sync(repo, campaign.id, tmp_path)

    exports = repo.list_campaign_exports_for_campaign(campaign.id)
    assert len(exports) == 2
    latest_manifest = exports[-1]["manifest"]
    assert set(latest_manifest.keys()) == {"file_counts", "bytes", "synced_at"}
    assert latest_manifest["file_counts"]["sources"] == 1
    assert latest_manifest["file_counts"]["chunks"] == 1
    assert latest_manifest["bytes"]["graph"] > 0
    assert exports[-1]["export_path"].endswith("/pinned/rag")


def test_readme_contains_title_and_slug(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="ReadableCampaign", min_n=3, max_n=6)
    rag_dir = _run_sync(repo, campaign.id, tmp_path)
    readme = (rag_dir / "README.md").read_text(encoding="utf-8")
    assert "ReadableCampaign" in readme
    assert "pinned" in readme
    assert "SurrealDB is the source of truth" in readme


def test_sync_unknown_campaign_raises(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    with pytest.raises(KeyError):
        asyncio.run(
            sync_campaign_rag_folder(
                campaign_id="campaign-missing",
                repository=repo,
                root=tmp_path,
            )
        )

from __future__ import annotations

import asyncio
import json

import pytest

from agentic_survey.agents.tools.definitions import propose_search_queries_tool
from agentic_survey.agents.tools.registry import ToolDispatchError
from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.web_search.suggestions import (
    SearchSuggestionsRejected,
    assert_design_time,
    queue_proposed_queries,
)


def _setup_campaign(state: CampaignState = CampaignState.DESIGNING):
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10, state=state)
    return repo, campaign


def test_queue_proposed_queries_persists_searxng_suggestion_rows() -> None:
    repo, campaign = _setup_campaign()

    created_ids = queue_proposed_queries(
        campaign_id=campaign.id,
        queries=["scientific data lifecycle phases", "qualitative interview saturation"],
        repository=repo,
    )

    assert len(created_ids) == 2
    rows = repo.list_knowledge_sources(campaign.id)
    assert len(rows) == 2
    for source in rows:
        assert source.kind == "searxng_suggestion"
        assert source.status == "pending_approval"
        assert source.url is None
        assert "source=brain_b_designer" in source.rationale


def test_queue_proposed_queries_skips_blank_strings() -> None:
    repo, campaign = _setup_campaign()

    created_ids = queue_proposed_queries(
        campaign_id=campaign.id,
        queries=["", "   ", "real query"],
        repository=repo,
    )

    assert len(created_ids) == 1
    rows = repo.list_knowledge_sources(campaign.id)
    assert len(rows) == 1
    assert rows[0].title == "real query"


def test_assert_design_time_allows_draft_designing_reviewing() -> None:
    for state in (CampaignState.DRAFT, CampaignState.DESIGNING, CampaignState.REVIEWING):
        assert_design_time(state)  # no raise


def test_assert_design_time_rejects_live_and_monitoring() -> None:
    with pytest.raises(SearchSuggestionsRejected):
        assert_design_time(CampaignState.LIVE)
    with pytest.raises(SearchSuggestionsRejected):
        assert_design_time(CampaignState.MONITORING)


def test_tool_handler_queues_and_returns_count() -> None:
    captured: list[list[str]] = []

    def queue_sink(queries: list[str]) -> list[str]:
        captured.append(list(queries))
        return [f"ksrc-{i}" for i in range(len(queries))]

    tool = propose_search_queries_tool(queue_sink=queue_sink)
    arguments = json.dumps({"queries": ["alpha", "beta", "gamma"]})

    result = asyncio.run(tool.handler(json.loads(arguments)))

    assert result == {"queued_count": 3, "source_ids": ["ksrc-0", "ksrc-1", "ksrc-2"]}
    assert captured == [["alpha", "beta", "gamma"]]


def test_tool_handler_rejects_empty_queries_list() -> None:
    tool = propose_search_queries_tool(queue_sink=lambda q: [])

    with pytest.raises(ValueError):
        asyncio.run(tool.handler({"queries": []}))


def test_tool_handler_rejects_non_string_query() -> None:
    tool = propose_search_queries_tool(queue_sink=lambda q: [])

    with pytest.raises(ValueError):
        asyncio.run(tool.handler({"queries": ["ok", 42]}))


def test_tool_handler_propagates_rejection_via_registry() -> None:
    """When the queue_sink raises (e.g. campaign is LIVE), the registry
    surfaces a ``ToolDispatchError`` so Brain B sees the failure on the
    next iteration instead of silently succeeding."""
    from agentic_survey.agents.tools.registry import ToolRegistry

    def raising_sink(queries: list[str]) -> list[str]:
        raise SearchSuggestionsRejected("campaign is live")

    registry = ToolRegistry([propose_search_queries_tool(queue_sink=raising_sink)])

    with pytest.raises(ToolDispatchError) as exc:
        asyncio.run(registry.dispatch("propose_search_queries", {"queries": ["q"]}))
    assert "campaign is live" in str(exc.value)


def test_interviewer_registry_does_not_include_propose_search_queries() -> None:
    """Invariant regression: the Interviewer surface never has web search."""
    from agentic_survey.agents.brain_b_interviewer import run_brain_b_interviewer  # noqa: F401
    import agentic_survey.agents.brain_b_interviewer as interviewer_mod

    source = interviewer_mod.__file__
    with open(source, "r", encoding="utf-8") as f:
        body = f.read()
    assert "propose_search_queries" not in body

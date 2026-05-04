from __future__ import annotations

import asyncio
import logging

from agentic_survey.agents.validator import Validator
from agentic_survey.engine.event_bus import CampaignEventBus
from agentic_survey.engine.interview_loop import (
    run_post_turn_background,
    run_pre_plan_background,
)
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.llm.router import LiteLLMRouter
from agentic_survey.repository import InMemoryRepository

__all__ = [
    "spawn_post_turn_bg",
    "spawn_pre_plan_bg",
]


logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[None]] = set()
_pre_plan_tasks_by_session: dict[str, asyncio.Task[None]] = {}


def _track(task: asyncio.Task[None]) -> None:
    """Keep a hard reference to a fire-and-forget task until it finishes."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def spawn_post_turn_bg(
    *,
    session_id: str,
    campaign_id: str,
    participant_turn_id: str,
    agent_turn_id: str,
    repository: InMemoryRepository,
    router: LiteLLMRouter,
    validator: Validator,
    cache: RetrievalCache,
    bus: CampaignEventBus,
) -> asyncio.Task[None]:
    task = asyncio.create_task(
        run_post_turn_background(
            session_id=session_id,
            campaign_id=campaign_id,
            participant_turn_id=participant_turn_id,
            agent_turn_id=agent_turn_id,
            repository=repository,
            router=router,
            validator=validator,
            cache=cache,
            bus=bus,
        )
    )
    _track(task)
    return task


def spawn_pre_plan_bg(
    *,
    session_id: str,
    campaign_id: str,
    repository: InMemoryRepository,
    router: LiteLLMRouter,
    cache: RetrievalCache,
    bus: CampaignEventBus,
) -> asyncio.Task[None]:
    existing = _pre_plan_tasks_by_session.get(session_id)
    if existing is not None and not existing.done():
        logger.info("pre-plan already in flight: session=%s", session_id)
        return existing

    logger.info("spawning pre-plan background task: session=%s campaign=%s", session_id, campaign_id)
    task = asyncio.create_task(
        run_pre_plan_background(
            session_id=session_id,
            campaign_id=campaign_id,
            repository=repository,
            router=router,
            cache=cache,
            bus=bus,
        )
    )
    _pre_plan_tasks_by_session[session_id] = task
    _track(task)

    def _clear_pre_plan(completed: asyncio.Task[None]) -> None:
        if _pre_plan_tasks_by_session.get(session_id) is completed:
            _pre_plan_tasks_by_session.pop(session_id, None)

    task.add_done_callback(_clear_pre_plan)
    return task

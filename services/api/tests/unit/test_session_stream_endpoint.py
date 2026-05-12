from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.api.sessions import _session_event_stream
from agentic_survey.engine.event_bus import get_event_bus, reset_event_bus
from agentic_survey.engine.interview_loop import InterviewEvent
from agentic_survey.repository import InMemoryRepository


class _FakeRequest:
    def __init__(self, disconnect_after_yields: int) -> None:
        self._remaining = disconnect_after_yields

    async def is_disconnected(self) -> bool:
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False


async def _drain(gen: Any) -> list[bytes]:
    out: list[bytes] = []
    async for chunk in gen:
        out.append(chunk)
    return out


def test_session_stream_replays_persisted_events_when_bus_ring_is_empty() -> None:
    reset_event_bus()
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Stream", min_n=3, max_n=6)
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot={},
        pinned_endpoint="chatter",
    )
    repo.record_interview_events(
        campaign_id=campaign.id,
        events=[
            InterviewEvent(name="participant_turn", data={"session_id": session.id, "turn_id": "t1"}),
            InterviewEvent(name="turn_complete", data={"session_id": session.id, "turn_id": "t2"}),
        ],
    )

    chunks = asyncio.run(
        _drain(
            _session_event_stream(
                campaign_id=campaign.id,
                session_id=session.id,
                request=_FakeRequest(disconnect_after_yields=2),
                since=-1,
                repository=repo,
            )
        )
    )

    assert b"event: participant_turn" in chunks[0]
    assert b"event: turn_complete" in chunks[1]
    assert b"id: 0" in chunks[0]
    assert b"id: 1" in chunks[1]


def test_session_stream_formats_transient_token_without_cursor_id() -> None:
    reset_event_bus()
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Stream", min_n=3, max_n=6)
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot={},
        pinned_endpoint="chatter",
    )

    async def main() -> bytes:
        gen = _session_event_stream(
            campaign_id=campaign.id,
            session_id=session.id,
            request=_FakeRequest(disconnect_after_yields=3),
            since=-1,
            repository=repo,
        )
        task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0)
        get_event_bus().publish_transient_many(
            campaign.id,
            [InterviewEvent(name="token", data={"session_id": session.id, "text": "hello"})],
        )
        chunk = await task
        await gen.aclose()
        return chunk

    chunk = asyncio.run(main())
    assert b"event: token" in chunk
    assert b"id:" not in chunk

"""In-process fan-out of ``InterviewEvent``s per campaign.

The interview loop emits structured events (``graph_delta``,
``turn_complete``, etc.) as part of each participant turn. The operator
graph view subscribes to a campaign's event stream so it can animate
new nodes and edges as they land.

Design:

- One subscriber queue per open SSE connection; many subscribers per
  campaign are allowed.
- One bounded ring buffer per campaign for replay. A late-joining client
  passes ``since=<seq>`` and receives every envelope with a higher seq
  that is still in the ring.
- Transient events are supported for live-only participant UI updates
  such as Brain A token chunks. They are delivered to current
  subscribers, never enter the replay ring, and carry no cursor id.
- Publishers are fire-and-forget and never block. A slow subscriber
  drops its own oldest queued event rather than slowing the turn loop.
- Envelope ``seq`` is monotonic per campaign; gaps in the sequence a
  client sees mean its own queue overflowed, not that events were lost
  from the ring.

Concurrency contract: all bus methods must be called from the FastAPI
asyncio event loop. No locks are taken because asyncio is single-threaded
and none of the methods ``await``; mutations of ``_next_seq``/``_rings``/
``_subs`` are atomic between yield points. If a future caller needs to
publish from a thread pool or cross-loop context, add an ``asyncio.Lock``
here before doing so; do not rely on the current lock-free posture.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from agentic_survey.engine.interview_loop import InterviewEvent

RING_SIZE = 200
QUEUE_SIZE = 64

logger = logging.getLogger(__name__)

__all__ = [
    "CampaignEventBus",
    "EventEnvelope",
    "get_event_bus",
    "reset_event_bus",
]


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """A published event with its assigned per-campaign sequence number."""

    seq: int
    name: str
    data: dict[str, Any]


class CampaignEventBus:
    def __init__(self, ring_size: int = RING_SIZE, queue_size: int = QUEUE_SIZE) -> None:
        self._ring_size = ring_size
        self._queue_size = queue_size
        self._next_seq: dict[str, int] = {}
        self._rings: dict[str, deque[EventEnvelope]] = {}
        self._subs: dict[str, set[asyncio.Queue[EventEnvelope]]] = {}

    def publish_many(self, campaign_id: str, events: list[InterviewEvent]) -> None:
        if not events:
            return
        ring = self._rings.setdefault(campaign_id, deque(maxlen=self._ring_size))
        subs = self._subs.get(campaign_id, set())
        next_seq = self._next_seq.get(campaign_id, 0)
        for event in events:
            envelope = EventEnvelope(seq=next_seq, name=event.name, data=event.data)
            next_seq += 1
            ring.append(envelope)
            for queue in list(subs):
                _offer(queue, envelope)
        self._next_seq[campaign_id] = next_seq

    def publish_many_with_sequences(
        self,
        campaign_id: str,
        events: list[InterviewEvent],
        sequences: list[int],
    ) -> None:
        if not events:
            return
        if len(events) != len(sequences):
            raise ValueError("events and sequences must have the same length")
        ring = self._rings.setdefault(campaign_id, deque(maxlen=self._ring_size))
        subs = self._subs.get(campaign_id, set())
        next_seq = self._next_seq.get(campaign_id, 0)
        for event, sequence in zip(events, sequences, strict=True):
            envelope = EventEnvelope(seq=sequence, name=event.name, data=event.data)
            next_seq = max(next_seq, sequence + 1)
            ring.append(envelope)
            for queue in list(subs):
                _offer(queue, envelope)
        self._next_seq[campaign_id] = next_seq

    def publish_transient_many(self, campaign_id: str, events: list[InterviewEvent]) -> None:
        """Deliver live-only events without adding replay/cursor state."""
        if not events:
            return
        subs = self._subs.get(campaign_id, set())
        if not subs:
            return
        for event in events:
            envelope = EventEnvelope(seq=-1, name=event.name, data=event.data)
            for queue in list(subs):
                _offer(queue, envelope)

    def replay(self, campaign_id: str, since: int) -> list[EventEnvelope]:
        ring = self._rings.get(campaign_id)
        if not ring:
            return []
        return [env for env in ring if env.seq > since]

    def latest_seq(self, campaign_id: str) -> int:
        ring = self._rings.get(campaign_id)
        if not ring:
            return -1
        return ring[-1].seq

    def subscribe(self, campaign_id: str) -> asyncio.Queue[EventEnvelope]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=self._queue_size)
        self._subs.setdefault(campaign_id, set()).add(queue)
        return queue

    def unsubscribe(self, campaign_id: str, queue: asyncio.Queue[EventEnvelope]) -> None:
        subs = self._subs.get(campaign_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            self._subs.pop(campaign_id, None)

    def subscriber_count(self, campaign_id: str) -> int:
        return len(self._subs.get(campaign_id, ()))


def _offer(queue: asyncio.Queue[EventEnvelope], envelope: EventEnvelope) -> None:
    """Non-blocking enqueue; if the subscriber is full, drop its oldest."""
    try:
        queue.put_nowait(envelope)
        return
    except asyncio.QueueFull:
        pass
    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:
        pass
    try:
        queue.put_nowait(envelope)
    except asyncio.QueueFull:
        logger.warning(
            "event_bus: dropping seq=%d name=%s for deeply-stuck subscriber",
            envelope.seq,
            envelope.name,
        )


@lru_cache(maxsize=1)
def get_event_bus() -> CampaignEventBus:
    return CampaignEventBus()


def reset_event_bus() -> None:
    """Drop the cached singleton; tests call this between cases."""
    get_event_bus.cache_clear()

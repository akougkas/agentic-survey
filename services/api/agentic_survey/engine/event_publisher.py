from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def persist_and_publish_events(
    *,
    repository: Any,
    bus: Any,
    campaign_id: str,
    events: list[Any],
) -> None:
    """Persist durable lifecycle events, then publish them to live SSE clients."""
    if not events:
        return
    records = repository.record_interview_events(campaign_id=campaign_id, events=events)
    sequences = [record.sequence for record in records]
    if hasattr(bus, "publish_many_with_sequences"):
        bus.publish_many_with_sequences(campaign_id, events, sequences)
    else:
        bus.publish_many(campaign_id, events)


def publish_transient_events(
    *,
    bus: Any,
    campaign_id: str,
    events: list[Any],
) -> None:
    """Publish participant-safe live events that should not be replayed or stored."""
    if not events:
        return
    bus.publish_transient_many(campaign_id, events)

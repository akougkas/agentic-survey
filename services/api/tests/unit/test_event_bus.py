"""Unit tests for the in-process campaign event bus."""

from __future__ import annotations

import asyncio

from agentic_survey.engine.event_bus import CampaignEventBus, EventEnvelope
from agentic_survey.engine.interview_loop import InterviewEvent


def _make_events(names: list[str]) -> list[InterviewEvent]:
    return [InterviewEvent(name=name, data={"n": i}) for i, name in enumerate(names)]


def test_publish_assigns_monotonic_seq() -> None:
    async def main() -> list[EventEnvelope]:
        bus = CampaignEventBus()
        q = bus.subscribe("cid")
        bus.publish_many("cid", _make_events(["a", "b", "c"]))
        return [q.get_nowait() for _ in range(3)]

    got = asyncio.run(main())
    assert [env.seq for env in got] == [0, 1, 2]
    assert [env.name for env in got] == ["a", "b", "c"]


def test_ring_replay_since() -> None:
    bus = CampaignEventBus()
    bus.publish_many("cid", _make_events(["a", "b", "c", "d"]))

    assert [env.seq for env in bus.replay("cid", since=-1)] == [0, 1, 2, 3]
    assert [env.seq for env in bus.replay("cid", since=1)] == [2, 3]
    assert bus.replay("cid", since=99) == []


def test_multiple_subscribers_all_receive() -> None:
    async def main() -> tuple[list[str], list[str]]:
        bus = CampaignEventBus()
        q1 = bus.subscribe("cid")
        q2 = bus.subscribe("cid")
        bus.publish_many("cid", _make_events(["x", "y"]))
        return (
            [q1.get_nowait().name for _ in range(2)],
            [q2.get_nowait().name for _ in range(2)],
        )

    got1, got2 = asyncio.run(main())
    assert got1 == ["x", "y"]
    assert got2 == ["x", "y"]


def test_unsubscribe_drops_queue() -> None:
    async def main() -> None:
        bus = CampaignEventBus()
        q = bus.subscribe("cid")
        assert bus.subscriber_count("cid") == 1
        bus.unsubscribe("cid", q)
        assert bus.subscriber_count("cid") == 0

    asyncio.run(main())


def test_ring_buffer_drops_oldest_when_full() -> None:
    bus = CampaignEventBus(ring_size=3)
    bus.publish_many("cid", _make_events(["a", "b", "c", "d", "e"]))
    envs = bus.replay("cid", since=-1)
    assert [env.seq for env in envs] == [2, 3, 4]
    assert bus.latest_seq("cid") == 4


def test_slow_subscriber_drops_oldest_not_publisher() -> None:
    """When a subscriber's queue fills, the next publish drops its oldest."""

    async def main() -> list[int]:
        bus = CampaignEventBus(queue_size=2)
        q = bus.subscribe("cid")
        # Fill the queue with 2, then overflow with a third.
        bus.publish_many("cid", _make_events(["a", "b", "c"]))
        # The slow subscriber should hold seq 1 and 2; seq 0 was dropped.
        return [q.get_nowait().seq for _ in range(q.qsize())]

    got = asyncio.run(main())
    assert got == [1, 2]


def test_latest_seq_reports_minus_one_for_unknown_campaign() -> None:
    bus = CampaignEventBus()
    assert bus.latest_seq("never-published") == -1
    bus.publish_many("cid", _make_events(["a"]))
    assert bus.latest_seq("cid") == 0


def test_publish_empty_list_is_noop() -> None:
    bus = CampaignEventBus()
    bus.publish_many("cid", [])
    assert bus.latest_seq("cid") == -1
    assert bus.replay("cid", since=-1) == []


def test_sequence_is_per_campaign() -> None:
    bus = CampaignEventBus()
    bus.publish_many("a", _make_events(["x", "y"]))
    bus.publish_many("b", _make_events(["p"]))
    bus.publish_many("a", _make_events(["z"]))
    assert [env.seq for env in bus.replay("a", since=-1)] == [0, 1, 2]
    assert [env.seq for env in bus.replay("b", since=-1)] == [0]

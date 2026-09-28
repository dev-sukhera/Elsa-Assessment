"""Leaderboard coalescing and back-pressure.

AI-ASSISTED (Claude Code).
"""

import asyncio
import json

from quiz_server.bus import LocalBus
from quiz_server.connection import Connection, TokenBucket
from quiz_server.hub import Hub
from quiz_server.observability import Metrics
from quiz_server.store import InMemoryStore


class RecordingSocket:
    def __init__(self, block: bool = False) -> None:
        self.sent: list[dict] = []
        self.closed_with: int | None = None
        self._gate = asyncio.Event()
        if not block:
            self._gate.set()

    async def send_text(self, data: str) -> None:
        await self._gate.wait()
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_with = code


def make_conn(ws, user_id, metrics, queue_size=64):
    return Connection(ws, quiz_id="Q", user_id=user_id, name=user_id, queue_size=queue_size,
                      metrics=metrics, rate_limiter=TokenBucket(100, 100))


async def test_burst_of_answers_is_coalesced_into_few_snapshots():
    store, bus, metrics = InMemoryStore(), LocalBus(), Metrics()
    hub = Hub(store, bus, metrics, interval_s=0.05, top_n=5)
    await hub.start()
    sockets = [RecordingSocket() for _ in range(20)]
    conns = [make_conn(ws, f"u{i:02d}", metrics) for i, ws in enumerate(sockets)]
    for c in conns:
        await store.add_participant("Q", c.user_id, c.user_id)
        await hub.register(c)
        c.start_writer()

    # 20 players x 10 answers = 200 state changes spread over ~0.4 s, yielding
    # to the event loop between each, like real traffic. Without coalescing the
    # flusher would push roughly one snapshot per change.
    started = asyncio.get_running_loop().time()
    for q in range(10):
        for c in conns:
            await store.record_answer("Q", c.user_id, f"q{q}", 10 + int(c.user_id[1:]))
            await hub.notify_changed("Q")
            await asyncio.sleep(0.002)
    duration = asyncio.get_running_loop().time() - started
    await asyncio.sleep(0.3)

    max_expected = int(duration / 0.05) + 3            # one per 50 ms window, plus slack
    for ws in sockets:
        boards = [m for m in ws.sent if m["type"] == "leaderboard"]
        assert 1 <= len(boards) <= max_expected, (len(boards), max_expected)   # not ~200
        final = boards[-1]
        assert final["top"][0] == {"rank": 1, "user_id": "u19", "name": "u19", "score": 290}
        assert final["total_participants"] == 20
    me = [m for m in sockets[0].sent if m["type"] == "leaderboard"][-1]["me"]
    assert me == {"rank": 20, "score": 100}
    await hub.stop()


async def test_slow_client_gets_latest_snapshot_only():
    metrics = Metrics()
    ws = RecordingSocket(block=True)
    conn = make_conn(ws, "slow", metrics)
    conn.start_writer()
    for v in range(10):
        conn.send_leaderboard(json.dumps({"type": "leaderboard", "version": v}))
    await asyncio.sleep(0)
    ws._gate.set()
    await asyncio.sleep(0.05)
    assert [m["version"] for m in ws.sent] in ([9], [0, 9])  # intermediates skipped
    conn.close()


async def test_stuck_client_is_disconnected_and_memory_is_bounded():
    metrics = Metrics()
    ws = RecordingSocket(block=True)  # never drains
    conn = make_conn(ws, "stuck", metrics, queue_size=8)
    writer = conn.start_writer()
    results = [conn.send({"type": "question", "i": i}) for i in range(20)]
    await asyncio.sleep(0.05)
    assert results.count(True) == 8          # queue bound respected, rest refused
    assert conn.overloaded
    assert ws.closed_with == 1013
    assert writer.cancelled() or writer.done()
    assert metrics.slow_consumer_disconnects._value.get() == 1


async def test_unregister_last_connection_unsubscribes():
    store, bus, metrics = InMemoryStore(), LocalBus(), Metrics()
    hub = Hub(store, bus, metrics, interval_s=0.01, top_n=5)
    conn = make_conn(RecordingSocket(), "a", metrics)
    await hub.register(conn)
    assert "Q" in bus._subs and hub.local_count("Q") == 1
    await hub.unregister(conn)
    assert "Q" not in bus._subs and hub.local_count("Q") == 0

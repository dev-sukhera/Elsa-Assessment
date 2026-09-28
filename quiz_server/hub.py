"""Connection hub and coalescing leaderboard broadcaster (one per server node).

Why coalesce? Naively, every accepted answer triggers a leaderboard push to
every participant: with N players answering at once that is O(N^2) messages.
Instead a quiz is only marked "dirty" when it changes, and a single flusher
loop publishes at most one snapshot per dirty quiz every
`leaderboard_interval_s` (100 ms by default). Cost becomes O(N) per interval
no matter how many answers arrive, while the board still feels instant.

Every snapshot carries the store's `version`, so clients can ignore any
snapshot older than one they already rendered.

A slow periodic resync (every `resync_interval_s`) marks all local quizzes
dirty, which heals any bus notification lost during a Redis blip. Unchanged
quizzes are skipped cheaply by comparing versions.

AI-ASSISTED (Claude Code). Coalescing verified in tests/test_hub.py (many
changes collapse into one flush) and by the load test numbers in the README.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from .bus import UpdateBus
from .connection import Connection
from .observability import Metrics
from .store import SessionStore

log = logging.getLogger("quiz.hub")

CLOSE_SERVICE_RESTART = 1012


class Hub:
    def __init__(self, store: SessionStore, bus: UpdateBus, metrics: Metrics, *,
                 interval_s: float, top_n: int, resync_interval_s: float = 5.0) -> None:
        self._store, self._bus, self._metrics = store, bus, metrics
        self._interval, self._top_n, self._resync = interval_s, top_n, resync_interval_s
        self._local: dict[str, set[Connection]] = {}
        self._dirty: set[str] = set()
        self._last_version: dict[str, int] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        bus.set_handler(self.mark_dirty)

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._flush_loop(), name="leaderboard-flusher")

    async def stop(self) -> None:
        for conns in self._local.values():
            for c in conns:
                with contextlib.suppress(Exception):
                    await c.ws.close(code=CLOSE_SERVICE_RESTART, reason="server restarting")
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # -- registry ----------------------------------------------------------
    async def register(self, conn: Connection) -> None:
        conns = self._local.setdefault(conn.quiz_id, set())
        first = not conns
        conns.add(conn)
        self._metrics.connections.inc()
        if first:
            await self._bus.subscribe(conn.quiz_id)

    async def unregister(self, conn: Connection) -> None:
        conns = self._local.get(conn.quiz_id)
        if not conns or conn not in conns:
            return
        conns.discard(conn)
        self._metrics.connections.dec()
        if not conns:
            del self._local[conn.quiz_id]
            self._last_version.pop(conn.quiz_id, None)
            self._dirty.discard(conn.quiz_id)
            await self._bus.unsubscribe(conn.quiz_id)

    def local_count(self, quiz_id: str) -> int:
        return len(self._local.get(quiz_id, ()))

    # -- change notification ----------------------------------------------
    def mark_dirty(self, quiz_id: str) -> None:
        if quiz_id in self._local:
            self._dirty.add(quiz_id)
            self._wake.set()

    async def notify_changed(self, quiz_id: str) -> None:
        """Called after a state change: tell every node (including this one)."""
        try:
            await self._bus.publish(quiz_id)
        except Exception:
            # Bus down: still update local players; resync heals other nodes.
            self._metrics.errors.labels("bus_publish").inc()
            log.exception("bus publish failed", extra={"quiz_id": quiz_id})
            self.mark_dirty(quiz_id)

    # -- snapshots ---------------------------------------------------------
    async def snapshot_for(self, conn: Connection) -> None:
        """Send one leaderboard immediately (used right after join)."""
        text = await self._build(conn.quiz_id, [conn])
        if text:
            conn.send_leaderboard(text[conn.user_id])

    async def _build(self, quiz_id: str, conns: list[Connection]) -> dict[str, str]:
        top, total, version = await self._store.leaderboard(quiz_id, self._top_n)
        user_ids = list({c.user_id for c in conns})
        ranks = await self._store.ranks(quiz_id, user_ids)
        # Serialise the shared part once, then append each user's own rank.
        shared = json.dumps({
            "type": "leaderboard",
            "quiz_id": quiz_id,
            "version": version,
            "total_participants": total,
            "top": [{"rank": e.rank, "user_id": e.user_id, "name": e.name, "score": e.score} for e in top],
        }, separators=(",", ":"))[:-1]
        out = {}
        for u in user_ids:
            rank, score = ranks.get(u, (None, 0))
            out[u] = f'{shared},"me":{json.dumps({"rank": rank, "score": score}, separators=(",", ":"))}}}'
        self._last_version[quiz_id] = version
        return out

    async def _flush_quiz(self, quiz_id: str) -> None:
        conns = list(self._local.get(quiz_id, ()))
        if not conns:
            return
        start = time.perf_counter()
        try:
            texts = await self._build(quiz_id, conns)
        except Exception:
            self._metrics.errors.labels("leaderboard_flush").inc()
            log.exception("leaderboard flush failed", extra={"quiz_id": quiz_id})
            self._dirty.add(quiz_id)  # retry next tick
            return
        for c in conns:
            c.send_leaderboard(texts[c.user_id])
        self._metrics.lb_sent.inc(len(conns))
        self._metrics.lb_flush.observe(time.perf_counter() - start)

    async def _changed_since_last(self, quiz_id: str) -> bool:
        version = await self._store.version(quiz_id)
        return version != self._last_version.get(quiz_id)

    async def _flush_loop(self) -> None:
        next_resync = time.monotonic() + self._resync
        while True:
            try:
                timeout = max(0.0, next_resync - time.monotonic())
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=timeout)
                self._wake.clear()
                if time.monotonic() >= next_resync:
                    next_resync = time.monotonic() + self._resync
                    for q in list(self._local):
                        with contextlib.suppress(Exception):
                            if await self._changed_since_last(q):
                                self._dirty.add(q)
                dirty, self._dirty = self._dirty, set()
                if dirty:
                    await asyncio.gather(*(self._flush_quiz(q) for q in dirty))
                # Coalescing window: changes arriving now wait for the next tick.
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._metrics.errors.labels("flush_loop").inc()
                log.exception("flush loop error")
                await asyncio.sleep(self._interval)

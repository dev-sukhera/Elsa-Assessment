"""One client WebSocket connection with back-pressure protection.

Outbound messages never block the code that produces them:

* Important messages (question, answer_result, error) go into a bounded queue.
  If a client is so slow that the queue fills up, the connection is closed with
  code 1013 ("try again later") instead of letting memory grow without bound.
  The client reconnects and resumes from server state.
* Leaderboard snapshots use a single "latest wins" slot. A slow client simply
  skips intermediate snapshots, which is correct because each one is complete.

A dedicated writer task per connection drains both, so one slow socket can
never stall the leaderboard broadcast for everyone else.

AI-ASSISTED (Claude Code): pattern proposed by the AI when asked how to stop a
slow client from stalling broadcasts. Verified by tests/test_connection.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Protocol

from .observability import Metrics

log = logging.getLogger("quiz.connection")

CLOSE_TRY_AGAIN_LATER = 1013


class SendsText(Protocol):
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int, clock=time.monotonic) -> None:
        self.rate, self.capacity, self._clock = rate_per_s, float(burst), clock
        self.tokens, self.updated = float(burst), clock()

    def allow(self) -> bool:
        now = self._clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Connection:
    def __init__(self, ws: SendsText, *, quiz_id: str, user_id: str, name: str,
                 queue_size: int, metrics: Metrics, rate_limiter: TokenBucket) -> None:
        self.ws = ws
        self.quiz_id, self.user_id, self.name = quiz_id, user_id, name
        self.rate_limiter = rate_limiter
        self._metrics = metrics
        self._max = queue_size
        self._queue: deque[str] = deque()
        self._pending_leaderboard: str | None = None
        self._wake = asyncio.Event()
        self._overloaded = False
        self._closed = False
        self._writer: asyncio.Task | None = None
        self._closer: asyncio.Task | None = None

    # -- producers (sync, never block) ------------------------------------
    def send(self, payload: dict[str, Any]) -> bool:
        if self._closed:
            return False
        if len(self._queue) >= self._max:
            self._overload()
            return False
        self._queue.append(json.dumps(payload, separators=(",", ":")))
        self._wake.set()
        return True

    def send_leaderboard(self, text: str) -> None:
        if self._closed:
            return
        if self._pending_leaderboard is not None:
            self._metrics.lb_dropped.inc()
        self._pending_leaderboard = text
        self._wake.set()

    def close(self) -> None:
        """Stop accepting messages; the writer flushes what is queued and exits."""
        self._closed = True
        self._wake.set()

    @property
    def overloaded(self) -> bool:
        return self._overloaded

    def _overload(self) -> None:
        # The writer may be stuck inside send_text on a dead or throttled
        # socket, so waiting for it to notice would never finish. Cancel it
        # and close the socket out of band.
        if self._overloaded:
            return
        self._overloaded = self._closed = True
        self._queue.clear()
        self._pending_leaderboard = None
        self._metrics.slow_consumer_disconnects.inc()
        log.warning("slow consumer disconnected", extra={"quiz_id": self.quiz_id, "user_id": self.user_id})
        if self._writer is not None:
            self._writer.cancel()
        self._closer = asyncio.create_task(self._force_close())

    async def _force_close(self) -> None:
        try:
            await asyncio.wait_for(self.ws.close(code=CLOSE_TRY_AGAIN_LATER, reason="send queue full"), 2.0)
        except Exception:
            pass

    # -- consumer ----------------------------------------------------------
    def start_writer(self) -> asyncio.Task:
        self._writer = asyncio.create_task(self._run_writer(), name=f"writer-{self.user_id}")
        return self._writer

    async def _run_writer(self) -> None:
        """Drain outbound messages until the connection closes."""
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._queue:
                    await self.ws.send_text(self._queue.popleft())
                if self._pending_leaderboard is not None:
                    text, self._pending_leaderboard = self._pending_leaderboard, None
                    await self.ws.send_text(text)
                if self._closed and not self._queue:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # socket already gone; the reader side cleans up
            self._closed = True

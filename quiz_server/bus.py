"""Update bus: tells every server node "quiz X changed".

Only a tiny notification crosses the bus, never scores. Each node then reads
the authoritative leaderboard from the store. That keeps the bus cheap and
means a lost notification is healed by the next one.

* LocalBus: single node, in-process.
* RedisBus: Redis pub/sub, one channel per quiz. A node subscribes only to
  quizzes that have at least one local connection, so traffic scales with
  where players are, not with the total number of quizzes.

AI-ASSISTED (Claude Code). Multi-node behaviour verified in
tests/test_multinode.py (two app instances sharing one fakeredis server).
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import logging
from typing import Callable

from redis.asyncio import Redis

log = logging.getLogger("quiz.bus")

Handler = Callable[[str], None]


class UpdateBus(abc.ABC):
    def __init__(self) -> None:
        self._handler: Handler = lambda quiz_id: None

    def set_handler(self, handler: Handler) -> None:
        self._handler = handler

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def publish(self, quiz_id: str) -> None: ...

    @abc.abstractmethod
    async def subscribe(self, quiz_id: str) -> None: ...

    @abc.abstractmethod
    async def unsubscribe(self, quiz_id: str) -> None: ...


class LocalBus(UpdateBus):
    def __init__(self) -> None:
        super().__init__()
        self._subs: set[str] = set()

    async def publish(self, quiz_id: str) -> None:
        if quiz_id in self._subs:
            self._handler(quiz_id)

    async def subscribe(self, quiz_id: str) -> None:
        self._subs.add(quiz_id)

    async def unsubscribe(self, quiz_id: str) -> None:
        self._subs.discard(quiz_id)


class RedisBus(UpdateBus):
    PREFIX = "quizupd:"

    def __init__(self, redis: Redis) -> None:
        super().__init__()
        self._r = redis
        self._pubsub = redis.pubsub()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._reader(), name="redis-bus-reader")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._pubsub.aclose()

    async def publish(self, quiz_id: str) -> None:
        await self._r.publish(self.PREFIX + quiz_id, b"1")

    async def subscribe(self, quiz_id: str) -> None:
        await self._pubsub.subscribe(self.PREFIX + quiz_id)

    async def unsubscribe(self, quiz_id: str) -> None:
        await self._pubsub.unsubscribe(self.PREFIX + quiz_id)

    async def _reader(self) -> None:
        backoff = 0.1
        while True:
            try:
                if not self._pubsub.subscribed:
                    await asyncio.sleep(0.05)
                    continue
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                backoff = 0.1
                if msg and msg["type"] == "message":
                    channel = msg["channel"]
                    channel = channel.decode() if isinstance(channel, bytes) else channel
                    self._handler(channel[len(self.PREFIX):])
            except asyncio.CancelledError:
                raise
            except Exception:
                # Redis blip: log, back off, keep going. redis-py re-subscribes
                # on reconnect; periodic resync in the hub covers any gap.
                log.exception("redis bus reader error; retrying", extra={"backoff_s": backoff})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

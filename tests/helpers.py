"""Shared test helpers: fake clock, fast settings, WebSocket receive with a
timeout, and a join() context manager.

AI-ASSISTED (Claude Code). recv() and the context-manager form of join()
were added after mutation testing showed failing tests hung instead of
failing (docs/AI_COLLABORATION.md, issue 5).
"""

import json
from contextlib import contextmanager

import anyio

from quiz_server.config import Settings

RECV_TIMEOUT_S = 5.0


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


FAST = Settings(leaderboard_interval_s=0.01, rate_limit_burst=1000, rate_limit_per_s=1000, log_level="WARNING")


def recv(ws, timeout: float = RECV_TIMEOUT_S):
    """ws.receive_json() with a timeout. Starlette's test session blocks
    forever, which turned a failing test into a hung test run (found while
    mutation-testing the suite). Uses the session's internals on purpose."""
    async def _get():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(_get)
    ws._raise_on_close(message)
    return json.loads(message["text"])


def recv_until(ws, msg_type, predicate=lambda m: True, limit=50):
    """Read messages until one of `msg_type` matches `predicate`. Returns
    (match, skipped messages). Fails instead of hanging forever."""
    skipped = []
    for _ in range(limit):
        msg = recv(ws)
        if msg["type"] == msg_type and predicate(msg):
            return msg, skipped
        skipped.append(msg)
    raise AssertionError(f"no {msg_type} message within {limit} messages; got {skipped}")


@contextmanager
def join(client, user_id, name=None, quiz_id="DEMO"):
    """Open a socket and consume the join handshake.

    Yields (ws, joined, first question or quiz_complete). A context manager so
    the socket is always closed, even when an assertion fails: an open socket
    otherwise blocks TestClient teardown and hangs the whole run."""
    with client.websocket_connect(f"/ws/quizzes/{quiz_id}?user_id={user_id}&name={name or user_id}") as ws:
        joined, _ = recv_until(ws, "joined")
        expected = "quiz_complete" if joined["me"]["answered"] == joined["quiz"]["question_count"] else "question"
        nxt, _ = recv_until(ws, expected, limit=5)
        yield ws, joined, nxt

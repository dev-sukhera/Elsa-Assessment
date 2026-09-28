"""Two server nodes sharing one Redis: a player on node A must see a score
from a player on node B. This is the horizontal-scaling claim, tested.

AI-ASSISTED (Claude Code). Uses fakeredis (one FakeServer shared by both
apps) because no Redis server is available in the dev environment.
"""

import fakeredis
from fastapi.testclient import TestClient

from quiz_server.app import create_app
from quiz_server.bus import RedisBus
from quiz_server.store.redis_store import RedisStore

from .helpers import FAST, FakeClock, join, recv_until


def make_node(server, clock):
    # Each app runs in its own event loop thread, so each needs its own client.
    redis = fakeredis.FakeAsyncRedis(server=server)
    return create_app(FAST, store=RedisStore(redis), bus=RedisBus(redis), clock=clock)


def test_score_on_node_b_reaches_leaderboard_on_node_a():
    server, clock = fakeredis.FakeServer(), FakeClock()
    with TestClient(make_node(server, clock)) as node_a, TestClient(make_node(server, clock)) as node_b:
        with join(node_b, "bob", "Bob") as (bob, _, _):
            with join(node_a, "alice", "Alice") as (alice, _, _):
                bob.send_json({"type": "answer", "question_id": "q1", "choice": 0})
                res, _ = recv_until(bob, "answer_result")
                assert res["points_awarded"] == 150

                lb, _ = recv_until(alice, "leaderboard", lambda m: m["top"][0]["score"] > 0, limit=100)
                assert lb["top"][0] == {"rank": 1, "user_id": "bob", "name": "Bob", "score": 150}
                assert lb["total_participants"] == 2
                assert lb["me"] == {"rank": 2, "score": 0}

            # Alice's node goes away; she reconnects to the OTHER node and
            # keeps her place in the quiz.
            with join(node_b, "alice", "Alice") as (_, joined, q):
                assert joined["rejoined"] is True and q["question"]["id"] == "q1"

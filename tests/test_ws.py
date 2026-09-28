"""End-to-end tests through the real WebSocket endpoint.

AI-ASSISTED (Claude Code): scenarios map one-to-one to the acceptance
criteria (join by quiz ID, multiple users, real-time score, live leaderboard)
plus the failure modes listed in DESIGN.md.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from quiz_server.app import create_app
from quiz_server.config import Settings
from quiz_server.scoring import BASE_POINTS, MAX_SPEED_BONUS

from .helpers import FAST, FakeClock, join, recv, recv_until


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(clock):
    with TestClient(create_app(FAST, clock=clock)) as c:
        yield c


def answer(ws, qid, choice, request_id=None):
    ws.send_json({"type": "answer", "question_id": qid, "choice": choice, "request_id": request_id})


# -- joining ---------------------------------------------------------------

def test_join_returns_state_first_question_and_leaderboard(client):
    with client.websocket_connect("/ws/quizzes/DEMO?user_id=alice&name=Alice") as ws:
        joined, _ = recv_until(ws, "joined")
        assert joined["quiz"] == {"id": "DEMO", "title": "Vocabulary Warm-up", "question_count": 5}
        assert joined["me"]["score"] == 0 and joined["rejoined"] is False
        q, skipped = recv_until(ws, "question")
        assert q["question"]["id"] == "q1"
        assert "correct_index" not in q["question"]  # never leak the answer
        lb = next((m for m in skipped if m["type"] == "leaderboard"), None) or recv_until(ws, "leaderboard")[0]
        assert lb["me"] == {"rank": 1, "score": 0}


def test_unknown_quiz_is_rejected(client):
    with client.websocket_connect("/ws/quizzes/NOPE?user_id=alice") as ws:
        assert recv(ws)["code"] == "quiz_not_found"
        with pytest.raises(WebSocketDisconnect) as exc:
            recv(ws)
        assert exc.value.code == 4404


@pytest.mark.parametrize("user_id", ["", "has space", "x" * 65, "<script>"])
def test_invalid_user_id_is_rejected(client, user_id):
    with client.websocket_connect(f"/ws/quizzes/DEMO?user_id={user_id}") as ws:
        assert recv(ws)["code"] == "bad_request"
        with pytest.raises(WebSocketDisconnect) as exc:
            recv(ws)
        assert exc.value.code == 4400


def test_created_quiz_can_be_joined_by_id(client):
    quiz_id = client.post("/api/quizzes", json={"title": "Friday"}).json()["quiz_id"]
    with join(client, "alice", quiz_id=quiz_id) as (ws, joined, q):
        assert joined["quiz"]["id"] == quiz_id and joined["quiz"]["title"] == "Friday"


# -- scoring ---------------------------------------------------------------

def test_correct_answer_scores_with_server_side_speed_bonus(client, clock):
    with join(client, "alice") as (ws, _, q):
        clock.advance(5)  # 5 of 20 seconds used -> 75% of the bonus
        answer(ws, "q1", 0, request_id="r1")
        res, _ = recv_until(ws, "answer_result")
        expected = BASE_POINTS + round(MAX_SPEED_BONUS * 0.75)
        assert res == {"type": "answer_result", "request_id": "r1", "question_id": "q1", "correct": True,
                       "correct_index": 0, "points_awarded": expected, "score": expected, "elapsed_s": 5.0,
                       "version": res["version"]}
        assert res["version"] > 0
        nxt, _ = recv_until(ws, "question")
        assert nxt["question"]["id"] == "q2"


def test_wrong_late_and_skipped_answers_score_zero(client, clock):
    with join(client, "alice") as (ws, _, _):
        answer(ws, "q1", 3)                       # wrong
        assert recv_until(ws, "answer_result")[0]["points_awarded"] == 0
        recv_until(ws, "question")
        clock.advance(25)                         # past the 20 s limit
        answer(ws, "q2", 1)                       # right, but late
        late, _ = recv_until(ws, "answer_result")
        assert late["correct"] is True and late["points_awarded"] == 0
        recv_until(ws, "question")
        answer(ws, "q3", None)                    # skipped / timed out
        skipped, _ = recv_until(ws, "answer_result")
        assert skipped["points_awarded"] == 0 and skipped["score"] == 0


def test_duplicate_answer_is_not_double_counted(client):
    with join(client, "alice") as (ws, _, _):
        answer(ws, "q1", 0)
        first, _ = recv_until(ws, "answer_result")
        answer(ws, "q1", 0)
        dup, _ = recv_until(ws, "error")
        assert dup["code"] == "already_answered" and dup["score"] == first["score"]


def test_cannot_answer_a_question_before_it_is_served(client):
    with join(client, "alice") as (ws, _, _):
        answer(ws, "q3", 2)
        assert recv_until(ws, "error")[0]["code"] == "question_not_served"
        answer(ws, "zzz", 0)
        assert recv_until(ws, "error")[0]["code"] == "unknown_question"
        answer(ws, "q1", 9)
        assert recv_until(ws, "error")[0]["code"] == "invalid_choice"


def test_full_quiz_ends_with_quiz_complete(client):
    with join(client, "alice") as (ws, _, q):
        for _ in range(5):
            answer(ws, q["question"]["id"], 0)
            recv_until(ws, "answer_result")
            msg = recv(ws)
            while msg["type"] == "leaderboard":
                msg = recv(ws)
            q = msg
        assert q["type"] == "quiz_complete"


# -- real-time leaderboard across users ------------------------------------

def test_other_players_see_leaderboard_update(client):
    with join(client, "alice", "Alice") as (alice, _, _):
        with join(client, "bob", "Bob") as (bob, _, _):
            answer(alice, "q1", 0)
            recv_until(alice, "answer_result")
            lb, _ = recv_until(bob, "leaderboard", lambda m: m["top"] and m["top"][0]["score"] > 0)
            assert lb["top"][0]["user_id"] == "alice" and lb["top"][0]["name"] == "Alice"
            assert lb["total_participants"] == 2
            assert lb["me"] == {"rank": 2, "score": 0}


def test_leaderboard_versions_never_go_backwards(client):
    with join(client, "alice") as (alice, _, q):
        with join(client, "bob") as (bob, _, _):
            for _ in range(3):
                answer(alice, q["question"]["id"], 0)
                recv_until(alice, "answer_result")
                q, _ = recv_until(alice, "question")
            final, seen = recv_until(bob, "leaderboard", lambda m: m["top"][0]["score"] > 0 and m["version"] >= 5)
            versions = [m["version"] for m in seen if m["type"] == "leaderboard"] + [final["version"]]
            assert versions == sorted(versions)


# -- reliability -------------------------------------------------------------

def test_reconnect_resumes_score_and_keeps_question_timer(client, clock):
    with join(client, "alice") as (ws, _, _):
        answer(ws, "q1", 0)
        score = recv_until(ws, "answer_result")[0]["score"]
        recv_until(ws, "question")   # q2 served now: its timer starts

    clock.advance(8)             # network drop for 8 s
    with join(client, "alice") as (ws, joined, q):
        assert joined["rejoined"] is True and joined["me"]["score"] == score
        assert q["question"]["id"] == "q2"
        assert q["time_remaining_s"] == pytest.approx(12.0)  # reconnecting does not reset the clock


def test_invalid_messages_do_not_drop_the_connection(client):
    with join(client, "alice") as (ws, _, _):
        ws.send_text("not json")
        assert recv_until(ws, "error")[0]["code"] == "bad_request"
        ws.send_json({"type": "teleport"})
        assert recv_until(ws, "error")[0]["code"] == "bad_request"
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")


def test_oversized_message_closes_with_1009(client):
    with join(client, "alice") as (ws, _, _):
        ws.send_text("x" * 10_000)
        with pytest.raises(WebSocketDisconnect) as exc:
            for _ in range(10):
                recv(ws)
        assert exc.value.code == 1009


def test_rate_limit(clock):
    settings = Settings(leaderboard_interval_s=0.01, rate_limit_burst=3, rate_limit_per_s=0.001, log_level="WARNING")
    with TestClient(create_app(settings, clock=clock)) as client:
        with join(client, "alice") as (ws, _, _):
            for _ in range(6):
                ws.send_json({"type": "ping"})
            err, skipped = recv_until(ws, "error")
            assert err["code"] == "rate_limited"
            assert sum(m["type"] == "pong" for m in skipped) == 3


# -- REST, health, metrics --------------------------------------------------

def test_rest_leaderboard_health_and_metrics(client):
    with join(client, "alice", "Alice") as (ws, _, _):
        answer(ws, "q1", 0)
        recv_until(ws, "answer_result")
        body = client.get("/api/quizzes/DEMO/leaderboard").json()
        assert body["top"][0]["user_id"] == "alice" and body["top"][0]["score"] > 0
        assert client.get("/api/quizzes/NOPE/leaderboard").status_code == 404
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200
        metrics = client.get("/metrics").text
        assert 'quiz_answers_total{outcome="correct"} 1.0' in metrics
        assert "quiz_ws_connections 1.0" in metrics

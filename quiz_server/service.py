"""Quiz participation logic: join, serve questions, score answers.

Kept separate from the WebSocket transport so it is easy to read and test.
The server is authoritative: clients only send a choice; correctness, timing
and points are all decided here.

AI-ASSISTED (Claude Code): generated from the protocol spec in DESIGN.md.
Verified by the end-to-end tests in tests/test_ws.py.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from .connection import Connection
from .hub import Hub
from .observability import Metrics
from .protocol import AnswerMsg, ErrorCode, error
from .quizzes import Quiz
from .scoring import score_answer
from .store import SessionStore

log = logging.getLogger("quiz.service")


class QuizService:
    def __init__(self, store: SessionStore, hub: Hub, metrics: Metrics,
                 clock: Callable[[], float] = time.time) -> None:
        # Wall-clock time (not monotonic) because served-at timestamps are
        # shared across nodes. Nodes must run NTP; skew only shifts the bonus.
        self._store, self._hub, self._metrics, self._clock = store, hub, metrics, clock

    async def join(self, conn: Connection, quiz: Quiz) -> None:
        is_new = await self._store.add_participant(quiz.id, conn.user_id, conn.name)
        state = await self._store.participant(quiz.id, conn.user_id)
        answered = state.answered if state else frozenset()
        conn.send({
            "type": "joined",
            "quiz": {"id": quiz.id, "title": quiz.title, "question_count": len(quiz.questions)},
            "me": {"user_id": conn.user_id, "name": conn.name,
                   "score": state.score if state else 0, "answered": len(answered)},
            "rejoined": not is_new,
        })
        await self._hub.register(conn)
        await self._hub.snapshot_for(conn)
        if is_new:
            await self._hub.notify_changed(quiz.id)
        await self._serve_next(conn, quiz, answered)
        self._metrics.joins.labels("rejoin" if not is_new else "new").inc()
        log.info("joined", extra={"quiz_id": quiz.id, "user_id": conn.user_id, "rejoin": not is_new})

    async def _serve_next(self, conn: Connection, quiz: Quiz, answered: frozenset[str]) -> None:
        index, question = next(
            ((i, q) for i, q in enumerate(quiz.questions) if q.id not in answered), (None, None)
        )
        if question is None:
            conn.send({"type": "quiz_complete", "quiz_id": quiz.id})
            return
        now = self._clock()
        # First-served time wins, so reconnecting does not restart the timer.
        served = await self._store.mark_served(quiz.id, conn.user_id, question.id, now)
        remaining = max(0.0, question.time_limit_s - (now - served))
        conn.send({
            "type": "question",
            "index": index,
            "total": len(quiz.questions),
            "question": question.public_view(),
            "time_remaining_s": round(remaining, 2),
        })

    async def answer(self, conn: Connection, quiz: Quiz, msg: AnswerMsg) -> None:
        received = self._clock()
        started = time.perf_counter()
        question = quiz.question(msg.question_id)
        if question is None:
            return self._reject(conn, msg, ErrorCode.UNKNOWN_QUESTION, "No such question in this quiz")
        if msg.choice is not None and msg.choice >= len(question.options):
            return self._reject(conn, msg, ErrorCode.INVALID_CHOICE, "Choice is out of range")
        served = await self._store.served_at(quiz.id, conn.user_id, question.id)
        if served is None:
            return self._reject(conn, msg, ErrorCode.NOT_SERVED, "Question has not been served to you yet")

        correct = msg.choice is not None and msg.choice == question.correct_index
        elapsed = received - served
        points = score_answer(correct=correct, elapsed_s=elapsed, time_limit_s=question.time_limit_s)
        outcome = await self._store.record_answer(quiz.id, conn.user_id, question.id, points)

        if not outcome.accepted:
            self._metrics.answers.labels("duplicate").inc()
            conn.send(error(ErrorCode.ALREADY_ANSWERED, "You already answered this question",
                            question_id=question.id, score=outcome.score, request_id=msg.request_id))
            return

        conn.send({
            "type": "answer_result",
            "request_id": msg.request_id,
            "question_id": question.id,
            "correct": correct,
            "correct_index": question.correct_index,
            "points_awarded": points,
            "score": outcome.score,
            "elapsed_s": round(elapsed, 3),
            # The first leaderboard with version >= this one includes this answer.
            "version": outcome.version,
        })
        self._metrics.answers.labels("correct" if correct else "incorrect").inc()
        self._metrics.answer_latency.observe(time.perf_counter() - started)
        log.info("answer", extra={"quiz_id": quiz.id, "user_id": conn.user_id, "question_id": question.id,
                                  "correct": correct, "points": points, "version": outcome.version})

        await self._hub.notify_changed(quiz.id)
        state = await self._store.participant(quiz.id, conn.user_id)
        await self._serve_next(conn, quiz, state.answered if state else frozenset({question.id}))

    def _reject(self, conn: Connection, msg: AnswerMsg, code: str, text: str) -> None:
        self._metrics.answers.labels("rejected").inc()
        conn.send(error(code, text, question_id=msg.question_id, request_id=msg.request_id))

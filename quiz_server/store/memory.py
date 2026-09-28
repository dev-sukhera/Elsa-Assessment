"""Single-node in-memory store.

Atomicity: every method runs to completion without awaiting, and asyncio is
single-threaded, so each call is atomic with respect to other coroutines.

AI-ASSISTED (Claude Code). Verified by tests/test_store_contract.py, which runs
the same suite against this store and the Redis store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import AnswerOutcome, LeaderboardEntry, ParticipantState, SessionStore


@dataclass
class _Session:
    names: dict[str, str] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)
    answers: dict[tuple[str, str], int] = field(default_factory=dict)
    answered_by: dict[str, set[str]] = field(default_factory=dict)
    served: dict[tuple[str, str], float] = field(default_factory=dict)
    version: int = 0
    # Cached ordering, invalidated whenever a score changes.
    _order: list[str] | None = None
    _rank_index: dict[str, int] | None = None

    def ordered(self) -> list[str]:
        if self._order is None:
            self._order = sorted(self.scores, key=lambda u: (-self.scores[u], u))
            self._rank_index = {u: i + 1 for i, u in enumerate(self._order)}
        return self._order

    def rank_of(self, user_id: str) -> int | None:
        self.ordered()
        assert self._rank_index is not None
        return self._rank_index.get(user_id)

    def invalidate(self) -> None:
        self._order = None
        self._rank_index = None


class InMemoryStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}

    def _s(self, quiz_id: str) -> _Session:
        return self._sessions.setdefault(quiz_id, _Session())

    async def add_participant(self, quiz_id: str, user_id: str, name: str) -> bool:
        s = self._s(quiz_id)
        s.names[user_id] = name
        if user_id in s.scores:
            return False
        s.scores[user_id] = 0
        s.version += 1
        s.invalidate()
        return True

    async def mark_served(self, quiz_id: str, user_id: str, question_id: str, ts: float) -> float:
        return self._s(quiz_id).served.setdefault((user_id, question_id), ts)

    async def served_at(self, quiz_id: str, user_id: str, question_id: str) -> float | None:
        return self._s(quiz_id).served.get((user_id, question_id))

    async def record_answer(self, quiz_id: str, user_id: str, question_id: str, points: int) -> AnswerOutcome:
        s = self._s(quiz_id)
        key = (user_id, question_id)
        if key in s.answers:
            return AnswerOutcome(accepted=False, score=s.scores.get(user_id, 0), version=s.version)
        s.answers[key] = points
        s.answered_by.setdefault(user_id, set()).add(question_id)
        s.scores[user_id] = s.scores.get(user_id, 0) + points
        s.version += 1
        s.invalidate()
        return AnswerOutcome(accepted=True, score=s.scores[user_id], version=s.version)

    async def participant(self, quiz_id: str, user_id: str) -> ParticipantState | None:
        s = self._sessions.get(quiz_id)
        if s is None or user_id not in s.scores:
            return None
        answered = frozenset(s.answered_by.get(user_id, ()))
        return ParticipantState(score=s.scores[user_id], answered=answered)

    async def leaderboard(self, quiz_id: str, top_n: int) -> tuple[list[LeaderboardEntry], int, int]:
        s = self._sessions.get(quiz_id)
        if s is None:
            return [], 0, 0
        top = [
            LeaderboardEntry(rank=i + 1, user_id=u, name=s.names.get(u, u), score=s.scores[u])
            for i, u in enumerate(s.ordered()[:top_n])
        ]
        return top, len(s.scores), s.version

    async def version(self, quiz_id: str) -> int:
        s = self._sessions.get(quiz_id)
        return s.version if s else 0

    async def ranks(self, quiz_id: str, user_ids: list[str]) -> dict[str, tuple[int, int]]:
        s = self._sessions.get(quiz_id)
        if s is None:
            return {}
        out: dict[str, tuple[int, int]] = {}
        for u in user_ids:
            rank = s.rank_of(u)
            if rank is not None:
                out[u] = (rank, s.scores[u])
        return out

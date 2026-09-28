"""Session state store contract.

All real-time state (participants, per-question timers, answers, scores,
leaderboard) lives behind this interface. Two implementations exist:

* InMemoryStore: single node, zero dependencies, used for dev and tests.
* RedisStore: shared by many stateless server nodes, used in production.

Both are run against the same contract tests (tests/test_store_contract.py),
so either can be swapped in without changing the server.

Ordering rule (both stores): higher score first, ties broken by user_id
ascending, so every node renders an identical leaderboard.

AI-ASSISTED (Claude Code): interface designed with the AI. The key decision is
that "dedupe + add points + bump version" is ONE atomic operation, so
concurrent or duplicate submissions can never double-count.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerOutcome:
    accepted: bool      # False when this user already answered this question
    score: int          # user's total score after the operation
    version: int        # quiz-wide monotonically increasing state version


@dataclass(frozen=True)
class LeaderboardEntry:
    rank: int           # 1-based
    user_id: str
    name: str
    score: int


@dataclass(frozen=True)
class ParticipantState:
    score: int
    answered: frozenset[str]


class SessionStore(abc.ABC):
    @abc.abstractmethod
    async def add_participant(self, quiz_id: str, user_id: str, name: str) -> bool:
        """Register a participant with score 0. Idempotent. Returns True if new."""

    @abc.abstractmethod
    async def mark_served(self, quiz_id: str, user_id: str, question_id: str, ts: float) -> float:
        """Record when a question was first sent to a user. Returns the FIRST
        recorded timestamp, so reconnecting cannot reset the timer."""

    @abc.abstractmethod
    async def served_at(self, quiz_id: str, user_id: str, question_id: str) -> float | None:
        ...

    @abc.abstractmethod
    async def record_answer(self, quiz_id: str, user_id: str, question_id: str, points: int) -> AnswerOutcome:
        """Atomically: reject if already answered, else store the answer, add
        points to the score and bump the quiz version."""

    @abc.abstractmethod
    async def participant(self, quiz_id: str, user_id: str) -> ParticipantState | None:
        ...

    @abc.abstractmethod
    async def leaderboard(self, quiz_id: str, top_n: int) -> tuple[list[LeaderboardEntry], int, int]:
        """Returns (top entries, total participants, version)."""

    @abc.abstractmethod
    async def version(self, quiz_id: str) -> int:
        """Current quiz state version (0 if unknown). Cheap change detection."""

    @abc.abstractmethod
    async def ranks(self, quiz_id: str, user_ids: list[str]) -> dict[str, tuple[int, int]]:
        """Batch lookup of (rank, score) for many users in one round trip."""

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

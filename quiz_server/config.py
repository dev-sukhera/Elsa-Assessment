"""Runtime configuration, read from environment variables.

AI-ASSISTED (Claude Code): generated from the design discussion; values were
tuned while running tests and the load test (see docs/AI_COLLABORATION.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # "memory" for a single node, "redis" for a horizontally scaled cluster.
    store_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"

    # Leaderboard fan-out is coalesced: at most one snapshot per quiz per interval.
    leaderboard_interval_s: float = 0.1
    leaderboard_top_n: int = 10

    # Per-connection protection.
    send_queue_size: int = 64
    rate_limit_per_s: float = 10.0
    rate_limit_burst: int = 20
    max_message_bytes: int = 4096

    # Session state expires so abandoned quizzes do not leak memory in Redis.
    session_ttl_s: int = 24 * 3600

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            store_backend=os.environ.get("QUIZ_STORE", cls.store_backend),
            redis_url=os.environ.get("QUIZ_REDIS_URL", cls.redis_url),
            leaderboard_interval_s=_env_float("QUIZ_LEADERBOARD_INTERVAL_S", cls.leaderboard_interval_s),
            leaderboard_top_n=_env_int("QUIZ_LEADERBOARD_TOP_N", cls.leaderboard_top_n),
            send_queue_size=_env_int("QUIZ_SEND_QUEUE_SIZE", cls.send_queue_size),
            rate_limit_per_s=_env_float("QUIZ_RATE_LIMIT_PER_S", cls.rate_limit_per_s),
            rate_limit_burst=_env_int("QUIZ_RATE_LIMIT_BURST", cls.rate_limit_burst),
            max_message_bytes=_env_int("QUIZ_MAX_MESSAGE_BYTES", cls.max_message_bytes),
            session_ttl_s=_env_int("QUIZ_SESSION_TTL_S", cls.session_ttl_s),
            log_level=os.environ.get("QUIZ_LOG_LEVEL", cls.log_level),
        )

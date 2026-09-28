"""Metrics (Prometheus) and structured JSON logging.

Each app instance gets its own CollectorRegistry so tests can build many apps
in one process without "duplicated timeseries" errors.

AI-ASSISTED (Claude Code): metric selection discussed with the AI; the list
maps one-to-one onto the alerts proposed in docs/DESIGN.md.
"""

from __future__ import annotations

import json
import logging
import sys
import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.connections = Gauge("quiz_ws_connections", "Open WebSocket connections", registry=r)
        self.joins = Counter("quiz_joins_total", "Quiz joins", ["result"], registry=r)
        self.messages_in = Counter("quiz_ws_messages_received_total", "Inbound messages", ["type"], registry=r)
        self.answers = Counter("quiz_answers_total", "Answer submissions", ["outcome"], registry=r)
        self.answer_latency = Histogram(
            "quiz_answer_processing_seconds", "Time from answer received to result queued",
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0), registry=r,
        )
        self.lb_flush = Histogram(
            "quiz_leaderboard_flush_seconds", "Time to build and enqueue one quiz leaderboard",
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5), registry=r,
        )
        self.lb_sent = Counter("quiz_leaderboard_messages_sent_total", "Leaderboard messages enqueued", registry=r)
        self.lb_dropped = Counter(
            "quiz_leaderboard_snapshots_superseded_total",
            "Leaderboard snapshots replaced by a newer one before a slow client received them", registry=r,
        )
        self.slow_consumer_disconnects = Counter(
            "quiz_slow_consumer_disconnects_total", "Connections closed because their send queue was full", registry=r,
        )
        self.errors = Counter("quiz_errors_total", "Errors by where they happened", ["where"], registry=r)


_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including any `extra={...}` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("quiz")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


class Timer:
    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.perf_counter() - self.start

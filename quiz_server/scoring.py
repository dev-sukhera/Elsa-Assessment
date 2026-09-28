"""Scoring rules. Pure functions with no I/O so they are trivially testable.

Rules:
* A wrong answer, or an answer after the time limit, scores 0.
* A correct answer scores BASE_POINTS plus a speed bonus that decays linearly
  from MAX_SPEED_BONUS (instant) to 0 (at the time limit).
* Elapsed time is measured on the SERVER, from when the question was first
  sent to that user. Client clocks are never trusted.

AI-ASSISTED (Claude Code): generated together with tests/test_scoring.py,
which pins the boundary cases (negative elapsed, exactly at the limit, late).
"""

from __future__ import annotations

BASE_POINTS = 100
MAX_SPEED_BONUS = 50


def score_answer(*, correct: bool, elapsed_s: float, time_limit_s: float) -> int:
    if not correct or time_limit_s <= 0:
        return 0
    elapsed_s = max(0.0, elapsed_s)  # guard against clock adjustments
    if elapsed_s > time_limit_s:
        return 0
    remaining_fraction = 1.0 - (elapsed_s / time_limit_s)
    return BASE_POINTS + round(MAX_SPEED_BONUS * remaining_fraction)

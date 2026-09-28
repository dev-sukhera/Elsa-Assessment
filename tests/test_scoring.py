"""AI-ASSISTED (Claude Code): cases enumerated with the AI, expected values
computed by hand from the rule in scoring.py."""

import pytest

from quiz_server.scoring import BASE_POINTS, MAX_SPEED_BONUS, score_answer


@pytest.mark.parametrize(
    "correct, elapsed, limit, expected",
    [
        (True, 0.0, 20.0, BASE_POINTS + MAX_SPEED_BONUS),   # instant
        (True, 10.0, 20.0, BASE_POINTS + 25),               # halfway
        (True, 20.0, 20.0, BASE_POINTS),                    # exactly at limit
        (True, 20.001, 20.0, 0),                            # late
        (True, -3.0, 20.0, BASE_POINTS + MAX_SPEED_BONUS),  # clock skew clamps to 0
        (False, 0.0, 20.0, 0),                              # wrong
        (True, 1.0, 0.0, 0),                                # misconfigured question
    ],
)
def test_score_answer(correct, elapsed, limit, expected):
    assert score_answer(correct=correct, elapsed_s=elapsed, time_limit_s=limit) == expected


def test_faster_never_scores_less():
    scores = [score_answer(correct=True, elapsed_s=t / 10, time_limit_s=20) for t in range(0, 201)]
    assert scores == sorted(scores, reverse=True)

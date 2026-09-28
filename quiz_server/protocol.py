"""WebSocket message schema.

Client -> server
    {"type": "answer", "question_id": "q1", "choice": 2, "request_id": "abc"}
        choice null = skipped / timed out (scores 0, moves on)
    {"type": "ping"}

Server -> client
    joined, question, answer_result, leaderboard, quiz_complete, pong, error
    (see docs/DESIGN.md, "WebSocket protocol")

AI-ASSISTED (Claude Code).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

USER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_NAME_LEN = 32


class AnswerMsg(BaseModel):
    type: Literal["answer"]
    question_id: str = Field(min_length=1, max_length=64)
    choice: int | None = Field(default=None, ge=0, le=31)
    request_id: str | None = Field(default=None, max_length=64)


class PingMsg(BaseModel):
    type: Literal["ping"]


ClientMessage = TypeAdapter(Annotated[Union[AnswerMsg, PingMsg], Field(discriminator="type")])


class ErrorCode:
    BAD_REQUEST = "bad_request"
    QUIZ_NOT_FOUND = "quiz_not_found"
    UNKNOWN_QUESTION = "unknown_question"
    NOT_SERVED = "question_not_served"
    INVALID_CHOICE = "invalid_choice"
    ALREADY_ANSWERED = "already_answered"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal_error"


def error(code: str, message: str, **extra: object) -> dict:
    return {"type": "error", "code": code, "message": message, **extra}


def clean_name(raw: str | None, fallback: str) -> str:
    name = " ".join((raw or "").split())[:MAX_NAME_LEN]
    return name or fallback

"""Standard response envelope.

Every endpoint returns ``{"data": ..., "error": ...}`` so clients parse one shape
regardless of outcome. ``error`` carries a human-readable sentence, never a bare
status code -- the messaging layer relays it to a person verbatim.
"""

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class Envelope(BaseModel):
    data: Any = None
    error: ErrorBody | None = None


def ok(data: Any = None) -> dict[str, Any]:
    return Envelope(data=data).model_dump()


def fail(code: str, message: str) -> dict[str, Any]:
    return Envelope(error=ErrorBody(code=code, message=message)).model_dump()

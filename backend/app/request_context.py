"""
Request context tracking for debugging and logging.
"""

from contextvars import ContextVar
from typing import Any
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str | None = None) -> str:
    if request_id is None:
        request_id = str(uuid4())
    _request_id.set(request_id)
    return request_id


def clear_request_id() -> None:
    _request_id.set(None)


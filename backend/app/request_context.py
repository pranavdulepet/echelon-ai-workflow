"""
Request context tracking for debugging and logging.
"""

from contextvars import ContextVar
from typing import Any
from uuid import uuid4

# Context variable for request ID
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Get the current request ID."""
    return _request_id.get()


def set_request_id(request_id: str | None = None) -> str:
    """Set the request ID. If None, generates a new one."""
    if request_id is None:
        request_id = str(uuid4())
    _request_id.set(request_id)
    return request_id


def clear_request_id() -> None:
    """Clear the current request ID."""
    _request_id.set(None)


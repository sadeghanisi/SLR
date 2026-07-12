"""Single-process admission guard for WebApp background jobs."""

import threading


CONFLICT_ERROR = "Another job is already running"
WORKSPACE_CONFLICT_ERROR = "Cannot change workspace while a job is running"

_lock = threading.Lock()
_active_job: str | None = None
_active_token: object | None = None


def try_reserve(kind: str) -> object | None:
    global _active_job, _active_token
    token = object()
    with _lock:
        if _active_token is not None:
            return None
        _active_job = kind
        _active_token = token
        return token


def release(token: object) -> None:
    global _active_job, _active_token
    with _lock:
        if _active_token is token:
            _active_job = None
            _active_token = None


def active_job() -> str | None:
    with _lock:
        return _active_job

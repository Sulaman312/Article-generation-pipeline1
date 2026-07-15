"""Cross-cutting cancel flags for background pipeline jobs.

Uses thread-local ContextVar so Anthropic/Perplexity helpers can abort without
every callsite threading an Event through the stack.

Jobs are process-local (in-memory). Deploy with a single Gunicorn worker so
cancel/job registries stay coherent across requests; active jobs are lost on
process restart (manifest statuses may be repaired as stale ``running``).
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_active_cancel: ContextVar[threading.Event | None] = ContextVar(
    "pipeline_cancel_event", default=None
)

# Durable registry (survives thread handoff within one process).
_EVENTS: dict[tuple[str, str, str], threading.Event] = {}
_EVENTS_LOCK = threading.Lock()


class JobCancelled(Exception):
    """Raised when a pipeline step is cancelled mid-flight."""


def get_or_create_event(key: tuple[str, str, str]) -> threading.Event:
    with _EVENTS_LOCK:
        event = _EVENTS.get(key)
        if event is None:
            event = threading.Event()
            _EVENTS[key] = event
        return event


def clear_event(key: tuple[str, str, str]) -> None:
    with _EVENTS_LOCK:
        _EVENTS.pop(key, None)


def request_cancel(key: tuple[str, str, str]) -> threading.Event:
    event = get_or_create_event(key)
    event.set()
    return event


def is_cancelled(event: threading.Event | None = None) -> bool:
    ev = event if event is not None else _active_cancel.get()
    return bool(ev and ev.is_set())


def raise_if_cancelled(event: threading.Event | None = None) -> None:
    if is_cancelled(event):
        raise JobCancelled("Pipeline step cancelled by user")


@contextmanager
def bind_cancel(event: threading.Event) -> Iterator[threading.Event]:
    token = _active_cancel.set(event)
    try:
        yield event
    finally:
        _active_cancel.reset(token)

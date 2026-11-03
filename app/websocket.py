"""Live log buffer for WebSocket streaming."""

import asyncio
from collections import deque
from core.timezone_utils import now_iso

_log_buffer: deque = deque(maxlen=500)
_subscribers: list[asyncio.Queue] = []
_main_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def _push_to_queue(q: asyncio.Queue, entry: dict) -> None:
    try:
        q.put_nowait(entry)
    except Exception:
        pass


def log(message: str) -> None:
    entry = {"time": now_iso(), "message": message}
    _log_buffer.append(entry)

    loop = _main_loop
    if loop and loop.is_running():
        for q in list(_subscribers):
            loop.call_soon_threadsafe(_push_to_queue, q, entry)
    else:
        for q in list(_subscribers):
            _push_to_queue(q, entry)


def get_recent(limit: int = 100) -> list[dict]:
    return list(_log_buffer)[-limit:]


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    for entry in list(_log_buffer)[-50:]:
        q.put_nowait(entry)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)

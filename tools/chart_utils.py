"""
Thread-safe sidecar queue for chart data.

Tools call push_chart() to enqueue structured chart data.
The streaming loop calls pop_charts() to drain the queue
and emit "chart" WebSocket messages alongside tool_result messages.
"""

import threading

_pending: list[dict] = []
_lock = threading.Lock()


def push_chart(data: dict) -> None:
    """Enqueue a chart payload from a tool call."""
    with _lock:
        _pending.append(data)


def pop_charts() -> list[dict]:
    """Drain and return all pending chart payloads (clears the queue)."""
    with _lock:
        out = list(_pending)
        _pending.clear()
        return out

"""
Thread-safe sidecar queues for tool-produced UI artifacts.

Tools call push_chart() / push_table() to enqueue structured payloads.
The streaming loop drains them after each tool_result event and emits them
as their own WebSocket frames alongside the textual tool_result, so the
frontend renders charts and tables from typed data instead of regex-parsing
the LLM's markdown.
"""

import threading

_pending_charts: list[dict] = []
_pending_tables: list[dict] = []
_lock = threading.Lock()


def push_chart(data: dict) -> None:
    """Enqueue a chart payload from a tool call."""
    with _lock:
        _pending_charts.append(data)


def pop_charts() -> list[dict]:
    """Drain and return all pending chart payloads (clears the queue)."""
    with _lock:
        out = list(_pending_charts)
        _pending_charts.clear()
        return out


def push_table(data: dict) -> None:
    """Enqueue a structured table payload from a tool call.

    Expected shape:
        {
          "title": str,
          "indicator": {
            "sdmx_id": int,
            "name": str,
            "unit": str,
            "source_url": str,
            "pdf_url": str,
          },
          "columns": [
            {"key": str, "label": str,
             "type": "period" | "region" | "number" | "percent",
             "unit": str | None,
             "decimals": int | None}
          ],
          "rows": [{<column key>: value, ...}],
        }
    Values in `rows` are typed (numbers as float/int, periods as strings,
    missing as None). The frontend handles locale formatting; the LLM still
    sees a textual summary returned by the tool for reasoning.
    """
    with _lock:
        _pending_tables.append(data)


def pop_tables() -> list[dict]:
    """Drain and return all pending table payloads (clears the queue)."""
    with _lock:
        out = list(_pending_tables)
        _pending_tables.clear()
        return out

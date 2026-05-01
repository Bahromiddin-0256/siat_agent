"""Lightweight per-request telemetry — JSON-lines log of agent runs.

Each run writes one line to `logs/agent.jsonl` capturing:
  - thread_id, started_at, duration_s
  - question (truncated)
  - tool calls (name + arg-shape only — full args may be PII)
  - llm token usage (in/out) when the provider exposes it
  - status (success | error)

This stays cheap (no DB, no async I/O) and lets you grep production behavior
later: which tools fail most, which queries are slow, where token budget
goes.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.logger import setup_logger

logger = setup_logger(__name__)

_LOG_PATH = Path("logs/agent.jsonl")
_LOG_LOCK = threading.Lock()


def _safe_arg_shape(args: Any) -> Any:
    """Reduce args to type info / lengths so we don't log raw user content."""
    if args is None:
        return None
    if isinstance(args, dict):
        return {k: _safe_arg_shape(v) for k, v in args.items()}
    if isinstance(args, (list, tuple)):
        return [_safe_arg_shape(v) for v in args[:5]]
    if isinstance(args, str):
        return args if len(args) <= 64 else args[:60] + "..."
    return args  # int, float, bool — fine to keep as-is


class RunTelemetry:
    """Collect events during a single agent run, then persist on close."""

    def __init__(self, thread_id: str, question: str):
        self.thread_id = thread_id
        self.question = question[:240]
        self.started_at = datetime.now().isoformat()
        self._t0 = time.monotonic()
        self.tools: list[dict] = []
        self.tokens_in: int = 0
        self.tokens_out: int = 0
        self.status: str = "success"
        self.error: str | None = None

    def record_tool_call(self, name: str | None, args: Any) -> None:
        self.tools.append({"name": name or "unknown", "args": _safe_arg_shape(args)})

    def record_token_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        # Different providers use different keys; check both common shapes.
        in_t = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        out_t = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        try:
            self.tokens_in += int(in_t)
            self.tokens_out += int(out_t)
        except (TypeError, ValueError):
            pass

    def fail(self, error: str) -> None:
        self.status = "error"
        self.error = error[:240]

    def close(self) -> None:
        record = {
            "thread_id": self.thread_id,
            "started_at": self.started_at,
            "duration_s": round(time.monotonic() - self._t0, 3),
            "question": self.question,
            "tool_count": len(self.tools),
            "tools": self.tools,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "status": self.status,
            "error": self.error,
        }
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_LOCK:
                with _LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"Telemetry write failed: {e}")

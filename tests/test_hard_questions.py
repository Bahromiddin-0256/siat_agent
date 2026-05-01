#!/usr/bin/env python3
"""Run a graded set of hard questions against the live WS endpoint.

Usage: python tests/test_hard_questions.py

Picks questions of increasing difficulty and reports the agent's tool chain
and final answer. Each question gets a 180s timeout so a stuck run doesn't
hang the whole suite.
"""
import asyncio
import json
import sys
import time

import websockets

URI = "ws://localhost:8001/ws"
PER_QUESTION_TIMEOUT = 180.0

QUESTIONS = [
    ("L1-region",      "2020-yildan beri Toshkent shahar aholisi qancha o'sgan, mutlaq sonda va foizda?"),
    ("L2-two-indic",   "2023-yilda O'zbekistonda har 1000 kishiga to'g'ri keladigan tug'ilganlar koeffitsientini hisoblang."),
    ("L2-quarterly",   "2025-yilning 3-choragida o'lim sabablari ichida eng yuqori va eng past ulushga ega kategoriyalarning farqi necha barobar?"),
    ("L4-english",     "What was the unemployment rate in Tashkent city in Q2 2025?"),
    ("L5-nonsense",    "Qoraqalpog'istonning 2024-yildagi YIM hissasi ekologiya statistikasiga qancha?"),
]


async def run_question(label: str, query: str) -> dict:
    started = time.monotonic()
    tools: list[tuple[str, dict]] = []
    results: list[str] = []
    final = ""
    error = None

    try:
        async with websockets.connect(URI, max_size=2_000_000) as ws:
            await ws.send(query)
            async with asyncio.timeout(PER_QUESTION_TIMEOUT):
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type")
                    if t == "tool_start":
                        tools.append((msg.get("tool_name"), msg.get("tool_args") or {}))
                    elif t == "tool_result":
                        results.append(msg.get("tool_result", "") or "")
                    elif t == "response":
                        final = msg.get("content", "") or ""
                        break
                    elif t == "error":
                        error = msg.get("content")
                        break
    except (asyncio.TimeoutError, TimeoutError):
        error = f"timeout after {PER_QUESTION_TIMEOUT}s"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    return {
        "label": label,
        "query": query,
        "elapsed": time.monotonic() - started,
        "tools": tools,
        "results": results,
        "final": final,
        "error": error,
    }


def fmt_args(args: dict) -> str:
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) < 120 else s[:117] + "..."


def print_report(r: dict) -> None:
    print("=" * 78)
    print(f"[{r['label']}] {r['query']}")
    print(f"({r['elapsed']:.1f}s, {len(r['tools'])} tool calls)")
    print("-" * 78)
    if r["error"]:
        print(f"ERROR: {r['error']}")
    for i, ((name, args), result) in enumerate(zip(r["tools"], r["results"]), 1):
        print(f"  #{i} {name}({fmt_args(args)})")
        snippet = (result or "").splitlines()
        head = " | ".join(s.strip() for s in snippet[:3] if s.strip())
        if head:
            print(f"      → {head[:160]}")
    print()
    print("FINAL:")
    print(r["final"] or "(no final response)")
    print()


async def main() -> int:
    overall = []
    for label, q in QUESTIONS:
        r = await run_question(label, q)
        overall.append(r)
        print_report(r)
    print("=" * 78)
    print("SUMMARY")
    for r in overall:
        flag = "OK " if r["final"] and not r["error"] else "FAIL"
        print(f"  {flag}  {r['label']:<14} {len(r['tools'])} tools, {r['elapsed']:.1f}s")
    return 0 if all(r["final"] and not r["error"] for r in overall) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

#!/usr/bin/env python3
"""Run a graded set of hard questions against the live WS endpoint.

Usage: python tests/test_hard_questions.py

Picks questions of increasing difficulty and reports the agent's tool chain
and final answer. Each question gets a 180s timeout so a stuck run doesn't
hang the whole suite.
"""
import asyncio
import json
import re
import sys
import time

import websockets

URI = "ws://localhost:8001/ws"
PER_QUESTION_TIMEOUT = 180.0

QUESTIONS = [
    {
        "label": "L1-region",
        "query": "2020-yildan beri Toshkent shahar aholisi qancha o'sgan, mutlaq sonda va foizda?",
        # Tashkent population grew from ~2 571.7 (2020) to ~3 112.8 (2025) ming kishi.
        "must_contain": ["248", "Toshkent", "2020"],
        "must_match_any": [r"541", r"21[.,]0?\d?\s*%"],  # delta ≈541 ming, ≈21%
        "must_not_contain": [],
    },
    {
        "label": "L2-two-indic",
        "query": "2023-yilda O'zbekistonda har 1000 kishiga to'g'ri keladigan tug'ilganlar koeffitsientini hisoblang.",
        "must_contain": ["1000"],
        # Birth rate ≈ 26.7 per 1000. Allow 26.6–26.8.
        "must_match_any": [r"26[.,][6-8]"],
        "must_not_contain": [],
    },
    {
        "label": "L2-quarterly",
        "query": "2025-yilning 3-choragida o'lim sabablari ichida eng yuqori va eng past ulushga ega kategoriyalarning farqi necha barobar?",
        "must_contain": ["4530", "Qon aylanish"],
        # Correct ratio is 77 241 / 1 197 = 64.53. Reject the old wrong 17.86.
        "must_match_any": [r"64[.,]5\d?", r"64[.,]5"],
        "must_not_contain": [r"17[.,]8\d"],
    },
    {
        "label": "L4-english",
        "query": "What was the unemployment rate in Tashkent city in Q2 2025?",
        # Should admit data is unavailable (yearly only, not quarterly).
        "must_match_any": [r"yo'q|not available|emas|mavjud emas|quarterly"],
        "must_contain": [],
        "must_not_contain": [],
    },
    {
        "label": "L5-nonsense",
        "query": "Qoraqalpog'istonning 2024-yildagi YIM hissasi ekologiya statistikasiga qancha?",
        # Should ask for clarification, not silently reframe.
        "must_match_any": [r"aniqlash|clarif|aralash|ikki .*soha|qaysi.*ko'rsatkich"],
        "must_contain": [],
        "must_not_contain": [],
    },
]


def evaluate(spec: dict, final: str) -> tuple[bool, list[str]]:
    """Apply must_contain / must_match_any / must_not_contain rules."""
    failures: list[str] = []
    text = final or ""
    for s in spec.get("must_contain", []):
        if s not in text:
            failures.append(f"missing literal '{s}'")
    matchers = spec.get("must_match_any", [])
    if matchers and not any(re.search(p, text, re.IGNORECASE) for p in matchers):
        failures.append(f"none of patterns matched: {matchers}")
    for p in spec.get("must_not_contain", []):
        if re.search(p, text, re.IGNORECASE):
            failures.append(f"forbidden pattern matched: {p}")
    return (len(failures) == 0, failures)


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
    for spec in QUESTIONS:
        r = await run_question(spec["label"], spec["query"])
        passed, failures = evaluate(spec, r["final"])
        r["passed"] = passed and not r["error"]
        r["failures"] = failures
        overall.append(r)
        print_report(r)
        if failures:
            print("  ASSERTION FAILURES:")
            for f in failures:
                print(f"    - {f}")
            print()

    print("=" * 78)
    print("SUMMARY")
    for r in overall:
        flag = "PASS" if r["passed"] else "FAIL"
        extra = f"  ({'; '.join(r['failures'])})" if r.get("failures") else ""
        print(f"  {flag}  {r['label']:<14} {len(r['tools'])} tools, {r['elapsed']:.1f}s{extra}")
    failures = [r for r in overall if not r["passed"]]
    print(f"\n{len(overall) - len(failures)}/{len(overall)} passed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

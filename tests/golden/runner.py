"""CLI runner for the SIAT golden eval set.

Posts each question in dataset.jsonl to a /chat endpoint, runs the typed
assertions, and writes a JSON results blob with per-question detail plus
aggregated metrics by category.

Usage:
  uv run python tests/golden/runner.py \\
    --endpoint http://172.16.8.39:8001/chat \\
    --out tests/golden/baselines/$(date +%Y%m%d-%H%M).json

Optional:
  --filter category=age_range,subset_selection
  --concurrency 4
  --limit 5            (smoke-test first N entries)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.golden import grader  # noqa: E402


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{i} invalid JSON: {e}") from e
    return entries


def _apply_filter(entries: list[dict], filter_str: str | None) -> list[dict]:
    if not filter_str:
        return entries
    selections: dict[str, set[str]] = defaultdict(set)
    for part in filter_str.split(","):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        selections[key.strip()].add(val.strip())
    out = []
    for e in entries:
        ok = True
        for key, vals in selections.items():
            if str(e.get(key)) not in vals:
                ok = False
                break
        if ok:
            out.append(e)
    return out


def _run_one(
    entry: dict[str, Any], endpoint: str, timeout_s: float
) -> dict[str, Any]:
    started = time.time()
    response_text = ""
    error: str | None = None
    try:
        r = httpx.post(
            endpoint,
            json={"message": entry["question"]},
            timeout=timeout_s,
        )
        r.raise_for_status()
        response_text = r.json().get("response", "")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    duration = time.time() - started

    results: list[dict[str, Any]] = []
    if error is None:
        for a in entry.get("assertions", []):
            try:
                passed, detail = grader.grade(a, response_text, duration)
            except Exception as exc:  # grader bug, not agent bug
                passed, detail = False, f"GRADER_ERROR: {exc}"
            results.append(
                {"type": a.get("type"), "passed": passed, "detail": detail if not passed else ""}
            )
    else:
        results.append({"type": "request", "passed": False, "detail": error})

    return {
        "id": entry["id"],
        "category": entry.get("category", "unknown"),
        "lang": entry.get("lang", "?"),
        "question": entry["question"],
        "duration_s": round(duration, 2),
        "response": response_text,
        "error": error,
        "assertions": results,
        "passed": all(r["passed"] for r in results) if results else False,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    by_lang: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r["passed"])
        by_lang[r["lang"]].append(r["passed"])

    def stats(passes: list[bool]) -> dict[str, Any]:
        n = len(passes)
        p = sum(passes)
        return {"passed": p, "total": n, "rate": round(p / n, 3) if n else 0.0}

    total_passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    return {
        "total": {"passed": total_passed, "total": total, "rate": round(total_passed / total, 3) if total else 0.0},
        "by_category": {k: stats(v) for k, v in sorted(by_cat.items())},
        "by_language": {k: stats(v) for k, v in sorted(by_lang.items())},
    }


def _print_summary(summary: dict, rows: list[dict[str, Any]]) -> None:
    t = summary["total"]
    print(f"\n=== TOTAL: {t['passed']}/{t['total']} ({t['rate']*100:.1f}%) ===\n")

    print("By category:")
    for cat, s in summary["by_category"].items():
        bar = "█" * int(s["rate"] * 20)
        print(f"  {cat:20s} {s['passed']:>3}/{s['total']:<3} {bar:<20} {s['rate']*100:>5.1f}%")

    print("\nBy language:")
    for lang, s in summary["by_language"].items():
        print(f"  {lang:5s} {s['passed']:>3}/{s['total']:<3} {s['rate']*100:>5.1f}%")

    failures = [r for r in rows if not r["passed"]]
    if failures:
        print(f"\n=== {len(failures)} FAILURE(S) ===\n")
        for f in failures:
            print(f"  [{f['category']:18s}] {f['id']}")
            print(f"    Q: {f['question']}")
            for a in f["assertions"]:
                if not a["passed"]:
                    print(f"    ✗ {a['type']}: {a['detail']}")
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description="SIAT golden eval runner")
    parser.add_argument("--endpoint", default="http://172.16.8.39:8001/chat")
    parser.add_argument("--dataset", default=str(Path(__file__).parent / "dataset.jsonl"))
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--filter", default=None, help="key=val,key=val (e.g. category=age_range)")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    entries = _load_dataset(dataset_path)
    entries = _apply_filter(entries, args.filter)
    if args.limit:
        entries = entries[: args.limit]
    print(f"Running {len(entries)} questions against {args.endpoint} "
          f"with concurrency={args.concurrency}...\n")

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        future_map = {
            pool.submit(_run_one, e, args.endpoint, args.timeout): e for e in entries
        }
        for fut in as_completed(future_map):
            r = fut.result()
            mark = "✓" if r["passed"] else "✗"
            print(f"  {mark} [{r['category']:18s}] {r['id']:35s} {r['duration_s']:>5.1f}s")
            rows.append(r)

    rows.sort(key=lambda r: (r["category"], r["id"]))
    summary = _summarize(rows)
    _print_summary(summary, rows)

    out_path.write_text(
        json.dumps(
            {"endpoint": args.endpoint, "summary": summary, "rows": rows},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\nWrote: {out_path}")
    return 0 if summary["total"]["rate"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())

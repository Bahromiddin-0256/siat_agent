# Golden evaluation set for SIAT agent

Assertion-based regression dataset that hits the live `/chat` endpoint and
grades the response against typed checks. Not a pytest suite — it's slow
(seconds per query) and depends on a running agent.

## Files

- `dataset.jsonl` — one question per line with assertions
- `runner.py` — CLI: POSTs each question, runs assertions, saves results
- `grader.py` — typed assertion implementations
- `baselines/<timestamp>.json` — captured runs (committed)

## Usage

```bash
uv run python tests/golden/runner.py \
  --endpoint http://172.16.8.39:8001/chat \
  --out tests/golden/baselines/$(date +%Y%m%d-%H%M).json
```

Optional flags: `--filter category=age_range` to run a subset; `--concurrency N`
to parallelise.

## Assertion types

| Type | Fields | Meaning |
|---|---|---|
| `language` | `expected` | Response detected language matches (uz/ru/en) |
| `indicator_in` | `ids` | At least one of these SDMX IDs cited in response |
| `indicator_not_in` | `ids`, `reason` | None of these SDMX IDs cited (e.g., urban-only when total asked) |
| `contains` | `text`, `case_sensitive?` | Substring must appear |
| `not_contains` | `text` | Substring must NOT appear |
| `says_unavailable` | `lang_hints` | Response acknowledges data not available |
| `table_min_rows` | `n` | Markdown table has ≥ N data rows |
| `max_seconds` | `n` | Response time under N seconds |
| `no_fabricated_total` | `value`, `tolerance` | Response must NOT contain a specific wrong number |

## Adding questions

Append a line to `dataset.jsonl`. Each entry needs `id`, `category`,
`lang`, `question`, and `assertions`. Use `notes` to record the failure
mode being checked.

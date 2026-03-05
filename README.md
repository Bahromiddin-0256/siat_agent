# SIAT Agent

An intelligent statistical data agent for Uzbekistan's State Statistics Committee (SIAT).
The agent answers questions about statistical indicators in Uzbek, Russian, and English
using a multi-tool ReAct pipeline backed by hybrid semantic search.

## Overview

Users ask natural-language questions such as:

> "2013-yil Andijon viloyatida nechta bola tug'ilgan?"

The agent:
1. Finds the relevant SDMX indicator ID via **BGE-M3 hybrid search** (dense + sparse RRF)
2. Extracts the exact data value from local SDMX JSON files
3. Returns a concise answer: *"Andijon viloyatida 2013-yil 64 239 ta bola tug'ilgan."*

---

## Architecture

```
User question (Uzbek / Russian / English)
          │
          ▼
   LangGraph ReAct Agent
          │
   ┌──────┴──────────────────────────────────────────┐
   │                   Tool Belt                      │
   │  ┌────────────────────────────────────────────┐ │
   │  │  Search & Discovery                        │ │
   │  │  • search_sdmx_semantic   (BGE-M3 + RRF)  │ │
   │  │  • search_sdmx_with_score (dense cosine)  │ │
   │  │  • search_sdmx_metadata   (methodology)   │ │
   │  │  • get_sdmx_id            (keyword)       │ │
   │  │  • list_sdmx_categories                   │ │
   │  │  • count_reports_for_category             │ │
   │  ├────────────────────────────────────────────┤ │
   │  │  Data Extraction                           │ │
   │  │  • get_sdmx_value                         │ │
   │  │  • get_sdmx_metadata                      │ │
   │  ├────────────────────────────────────────────┤ │
   │  │  Statistical Analysis                      │ │
   │  │  • calculate_yearly_growth                 │ │
   │  │  • calculate_statistics                    │ │
   │  │  • calculate_cagr                          │ │
   │  │  • compare_regions / rank_regions          │ │
   │  │  • calculate_percentage_share              │ │
   │  │  • compare_years                           │ │
   │  │  • calculate_period_total                  │ │
   │  │  • calculate_moving_average                │ │
   │  └────────────────────────────────────────────┘ │
   └─────────────────────────────────────────────────┘
          │
   ┌──────┴─────────────────────────────┐
   │         Vector Store (Qdrant)       │
   │  Collection: sdmx_rag               │
   │  Collection: sdmx_metadata          │
   │  Vectors: dense (1024-d) + sparse   │
   │  Fusion: Reciprocal Rank Fusion     │
   └─────────────────────────────────────┘
          │
   ┌──────┴─────────────────────────────┐
   │      Embeddings: BGE-M3             │
   │  (BAAI/bge-m3 via FlagEmbedding)   │
   │  • Dense vectors  – 1024 dim        │
   │  • Sparse (lexical) weights         │
   └─────────────────────────────────────┘
```

### Vector Search — Hybrid with RRF

Both RAG collections use **Qdrant** in local file mode with two named vector fields:

| Field    | Type   | Size      | Distance |
|----------|--------|-----------|----------|
| `dense`  | float  | 1024-dim  | Cosine   |
| `sparse` | sparse | variable  | Dot      |

Queries run a Qdrant *Prefetch* for each vector type, then combine results with
**Reciprocal Rank Fusion (RRF)** — giving good recall for both semantic and
keyword-level matches across Uzbek, Russian, and English text.

---

## Project Structure

```
siat_agent/
├── core/
│   ├── agent.py          # LangGraph ReAct agent + system prompt
│   ├── llm.py            # LLM provider selection (ollama/groq/deepinfra/open_router)
│   ├── settings.py       # Pydantic settings (reads .env)
│   └── logger.py         # Structured logging
├── tools/
│   ├── embedder.py       # BGE-M3 singleton (thread-safe lazy load)
│   ├── rag_tool.py       # sdmx_rag collection + search tools
│   ├── metadata_rag_tool.py  # sdmx_metadata collection + search tool
│   ├── sdmx_tool.py      # Keyword search over jsons/main.json
│   ├── sdmx_data_retrieval_tool.py  # Data value extraction from local files
│   ├── sdmx_statistics_tool.py      # Time-series & regional analysis tools
│   ├── sdmx_count_tool.py           # Report counting tools
│   └── constants.py      # Region code mappings
├── jsons/
│   ├── main.json         # SDMX indicator catalog
│   └── sdmxs/            # Per-indicator data files (sdmx_data_NNN.json)
├── static/
│   └── chat.html         # Web chat UI
├── vector/
│   └── qdrant/           # Persisted Qdrant collections (git-ignored)
├── main.py               # FastAPI app (lifespan, /chat, /ws, /health)
├── pyproject.toml        # Dependencies
├── Dockerfile
└── .env.example
```

---

## Setup

### Prerequisites

- Python 3.10+
- An LLM provider (Ollama locally, or API key for Groq / DeepInfra / OpenRouter)
- `jsons/main.json` — the SDMX indicator catalog

### Install

```bash
# Using uv (recommended)
uv pip install -e .

# Or pip
pip install -e .
```

BGE-M3 (`BAAI/bge-m3`) is downloaded from HuggingFace Hub on first startup
and cached locally. A GPU is not required but will speed up indexing.

### Configure

```bash
cp .env.example .env
# Edit .env with your provider credentials
```

Minimal `.env` for Ollama:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2
```

Minimal `.env` for Groq:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

Optional BGE-M3 override (use a local path or different HF model):

```env
BGE_M3_MODEL=/path/to/local/bge-m3
```

### Run

```bash
python main.py
# Open http://localhost:8000
```

On first run the agent builds two Qdrant collections from the SDMX data.
This takes a few minutes. Subsequent restarts load from the persisted
`vector/qdrant/` directory and start in seconds.

---

## API

### `POST /chat`

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Toshkent shahri 2022-yil aholi soni"}'
```

Response:

```json
{
  "response": "Toshkent shahrida 2022-yilda doimiy aholi soni ...",
  "status": "success"
}
```

### `GET /health`

Returns status of all subsystems:

```json
{
  "status": "healthy",
  "model": "llama3.2",
  "provider": "ollama",
  "checks": {
    "agent": true,
    "vector_store": true,
    "metadata_store": true,
    "json_data": true,
    "ollama": true
  }
}
```

### `WS /ws`

WebSocket endpoint for streaming responses. Messages are JSON:

```json
{"type": "tool_start", "tool_name": "search_sdmx_semantic", "tool_args": {...}, "timestamp": "..."}
{"type": "tool_result", "tool_result": "Found 5 indicators...", "timestamp": "..."}
{"type": "response", "content": "Final answer...", "timestamp": "..."}
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `FlagEmbedding` | BGE-M3 model (dense + sparse) |
| `qdrant-client` | Local vector store with hybrid search |
| `langchain` / `langgraph` | Agent framework |
| `fastapi` + `uvicorn` | HTTP + WebSocket server |
| `pydantic-settings` | Typed config from `.env` |

---

## Docker

```bash
docker build -t siat-agent .
docker run -p 8000:8000 --env-file .env siat-agent
```

---

## Data Format

`jsons/main.json` — hierarchical SDMX catalog:

```json
[
  {
    "id": 1,
    "code": "1.01",
    "name": "Demografiya",
    "name_en": "Demographics",
    "name_ru": "Демография",
    "name_uz": "Demografiya",
    "children": [
      {
        "id": 223,
        "code": "1.01.001",
        "name": "Tug'ilganlar soni (jami)",
        "period": "Yillik",
        "department": "Demografiya bo'limi",
        "status": "Active"
      }
    ]
  }
]
```

Per-indicator data files live at `jsons/sdmxs/sdmx_data_NNN.json`.

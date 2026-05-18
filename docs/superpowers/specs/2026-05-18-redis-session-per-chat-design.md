# Redis-backed Session per Chat — Design

**Status:** approved (2026-05-18)
**Author:** brainstorming session with bahromiddin
**Related code:** `core/agent.py`, `main.py`, `core/settings.py`, `static/chat.html`, `docker-compose.yml`

## Goal

Replace the in-process `MemorySaver` LangGraph checkpointer with a Redis-backed
one so conversation state for each chat persists across HTTP requests,
WebSocket reconnects, and server restarts. Today every HTTP `/chat` call gets
a fresh random `thread_id` (no continuity at all) and every WebSocket
connection gets one (continuity only for the lifetime of the socket). After
this change, a chat is keyed by a `chat_id` the client owns, so reload,
reconnect, and restart all preserve history.

## Non-goals (explicit YAGNI)

- Multi-chat sidebar UI. The `chat_id` design supports it later, but we ship
  one chat per browser.
- Authentication / user accounts. `chat_id` is unauthenticated — anyone with
  the id can resume the chat. Fine for the current threat model (intranet
  deploy at the stats agency).
- Migrating existing in-memory chats. There are none persistent today,
  nothing to migrate.
- Cross-chat history search, exports, or admin tooling for inspecting Redis.

## Architecture

```
Client (browser localStorage chat_id)
  │
  ├── POST /chat   { message, chat_id? }     ──┐
  └── WS  /ws?chat_id=…                       ─┤
                                               ▼
                                  FastAPI → LangGraph agent
                                               │
                                  thread_id = chat_id
                                               ▼
                            AsyncRedisSaver (langgraph-checkpoint-redis)
                                               ▼
                                Redis  (key: checkpoint:{chat_id}:…)
```

- **Session identity.** `chat_id` is a UUIDv4 supplied by the client (stored
  in the browser `localStorage`). It is passed directly as the LangGraph
  `thread_id`. If a request arrives without one, the server mints one and
  returns it; subsequent calls from that client reuse it.
- **Persistence layer.** `langgraph-checkpoint-redis`'s `AsyncRedisSaver` —
  drop-in replacement for `MemorySaver` implementing the same
  `BaseCheckpointSaver` interface. It is initialised once in the FastAPI
  lifespan so the connection pool is shared across requests.
- **TTL.** Each successful turn refreshes a sliding 7-day idle expiry on the
  chat's Redis keys. Configurable via `REDIS_SESSION_TTL_SECONDS`. Every
  interaction resets the timer.
- **Connectivity.** Required at startup. If `REDIS_URL` is set but
  unreachable, startup fails loud (same pattern as the current config
  validator). No silent fallback — debugging "why did my chat reset?" is
  harder than debugging "server didn't start".

## Components and file-level changes

| File | Change |
|---|---|
| `pyproject.toml` | Add `langgraph-checkpoint-redis` and `redis[hiredis]` dependencies. |
| `core/settings.py` | Add `redis_url` (default `redis://localhost:6379/0`) and `redis_session_ttl_seconds` (default `604800` = 7 days). Validate at startup. |
| `core/session.py` (new) | Small module owning the checkpointer lifecycle: `init_checkpointer()`, `close_checkpointer()`, `touch_ttl(thread_id)`, and a `current_checkpointer()` accessor. Keeping it separate from `core/agent.py` so the agent factory stays single-purpose. `touch_ttl` uses `SCAN MATCH checkpoint:{thread_id}:*` + `EXPIRE` against the same key prefix `AsyncRedisSaver` writes — the implementation plan must verify the exact prefix shape (the library may use `checkpoint`, `writes`, and `checkpoint_blobs` namespaces, all need refreshing). |
| `core/agent.py` | `create_sdmx_agent()` accepts a `checkpointer` argument (instead of constructing `MemorySaver()` internally). After each successful turn in `run_agent_async`, `run_agent`, and `run_agent_async_stream`, call `touch_ttl(thread_id)` to refresh the sliding expiry. |
| `main.py` | Lifespan opens the Redis checkpointer on startup and closes it on shutdown. `/chat` reads `chat_id` from the request body (optional) and echoes the resolved id. `/ws` reads `chat_id` from the query string; first server-sent event is `{"type":"session","chat_id":"…"}`. The fallback (agent unavailable) path also propagates `chat_id`. |
| `static/chat.html` | On load: read `chat_id` from `localStorage` under key `siat_chat_id`; generate a UUIDv4 (`crypto.randomUUID()`) and store if absent. Include `chat_id` in every HTTP body and WS URL query string. |
| `docker-compose.yml` | Add a `redis:7-alpine` service with a named volume (`redis-data:/data`) and a healthcheck. Set `REDIS_URL=redis://redis:6379/0` for the app service. |
| `.env.example` | Document `REDIS_URL` and `REDIS_SESSION_TTL_SECONDS`. |
| `core/logger.py` / health | `/health` probes Redis with a short-timeout `PING` and reports a `redis` boolean. |
| `tests/` | Two new tests — see Testing section below. |

## API contract

**HTTP `POST /chat`** — request body:
```json
{ "message": "…", "chat_id": "uuid?" }
```
Response:
```json
{ "response": "…", "status": "success", "chat_id": "uuid" }
```
The `chat_id` field is always present in the response (echoed when supplied,
freshly minted when not). Existing clients that don't send `chat_id` keep
working but won't have continuity until they start sending the returned id.

**WebSocket `/ws?chat_id=uuid`** — `chat_id` is read from the query string.
First server-sent frame after `accept` is:
```json
{"type":"session","chat_id":"uuid","timestamp":"…"}
```
After that, the existing event stream (`tool_start`, `tool_result`, `chart`,
`response_chunk`, `response`, `quality_warning`, `error`) is unchanged.

## Failure modes and edge cases

1. **Redis unreachable at startup.** Lifespan raises and FastAPI fails to
   start (matches existing `validate_config()` behaviour). Logged with a
   clear error pointing at `REDIS_URL`.
2. **Redis goes down mid-request.** The active turn errors out and the
   client sees a `5xx` (HTTP) or `{"type":"error"}` (WS) frame. Subsequent
   restart fixes it. No half-state, no silent fallback.
3. **Malformed `chat_id`** (not a UUIDv4). Server rejects with HTTP `400` /
   WS error frame. Prevents key-injection-style abuse from a hostile
   client. UUID parse via `uuid.UUID(chat_id, version=4)`.
4. **Concurrent writes to the same `chat_id`** (e.g. user opens two tabs).
   LangGraph's checkpointer is last-writer-wins per checkpoint version. We
   document this in `core/session.py` but do not defend against it — one
   human at a keyboard is not true concurrent fan-out.
5. **TTL refresh failure** (Redis transient blip during `touch_ttl`).
   Logged at warning level, does NOT fail the turn. Worst case: the key
   expires on the original timer; user starts a new chat.

## Testing

Two integration tests using a local Redis (the docker-compose service or a
test fixture container):

1. `test_session_continuity_per_chat_id` — two consecutive `/chat` calls
   with the same `chat_id` see the prior turn in the checkpointer state.
2. `test_session_isolation_across_chat_ids` — two `/chat` calls with
   different `chat_id`s do not see each other's state.

Plus one unit test (no Redis needed):

3. `test_chat_id_validation_rejects_garbage` — `/chat` with `chat_id`
   `"<script>"` returns 400 without invoking the agent.

CI / dev: the existing `pytest` suite gains a `redis` fixture that skips
the integration tests when `REDIS_URL` isn't reachable, so contributors
without Redis locally aren't blocked.

## Rollout

1. Land the Redis service + dependencies + settings (no behaviour change).
2. Land the checkpointer swap + `chat_id` plumbing.
3. Land the frontend `localStorage` change.

Each step is independently reviewable; the agent keeps working after step 1
(Redis is provisioned but unused), after step 2 (server accepts and echoes
`chat_id`, but old clients still don't send one and behave as before), and
fully benefits after step 3.

## Load-bearing decisions (confirmed)

- `chat_id` source = browser `localStorage`, server falls back to minting.
- TTL = 7 days, sliding window, configurable.
- Hard-fail on Redis unreachable at startup; no degradation to
  `MemorySaver`.

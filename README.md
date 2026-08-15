# Taskloom

A distributed, asynchronous task-processing system: a FastAPI service accepts
tasks and hands them to Redis-backed queues; independent worker processes
pull from those queues and execute tasks without ever blocking the API.
A React dashboard lets you submit tasks and watch them move through their
lifecycle in real time.

Built iteratively, phase by phase — starting from the simplest possible task
type (a "sleep" task that just waits N seconds) to prove out the plumbing,
then layering on production concerns one at a time.

## Phase 1: Core pipeline

- FastAPI API: create/list/get tasks, health check
- Redis-backed queue (plain Redis lists/hashes — no Celery)
- Async worker(s) executing a `sleep` task type
- Task lifecycle: `PENDING` → `ACTIVE` → `COMPLETED` / `FAILED`
- React + Vite + Tailwind dashboard (polling-based live view)
- Docker Compose orchestration

## Phase 2: Retries + dead-letter queue

- Failed tasks retry with exponential backoff (`retry_backoff_base * 2^(attempt-1)`,
  default 3 total attempts: 2s then 4s between retries) instead of failing outright
- New `RETRY_SCHEDULED` status, tracked via a Redis sorted-set retry queue
  (`queue:retry`, score = when the retry becomes ready) so a delayed retry
  doesn't need to sit blocking anything
- A retry-promoter loop runs alongside the worker's main consume loop,
  moving ready retries back onto the pending queue — race-safe across
  multiple worker replicas via atomic `ZREM`
- Tasks that exhaust all attempts land in the dead-letter queue: status
  `FAILED`, with the last error preserved
- `POST /api/v1/tasks/{id}/retry` manually requeues a dead-lettered task,
  resetting its attempt count — surfaced as a Retry button in the dashboard
  for any `failed` row
- Added a `fail` task type (always raises) purely to exercise/demo this path
  without needing a real flaky dependency — pick it from the dashboard's
  task-type dropdown

## Phase 3: Live updates via Server-Sent Events

- Every task state change (create, active, completed, retry scheduled,
  failed, manual retry) is published as the full task record to a Redis
  pub/sub channel (`task:events`) — the mechanism the API (which serves the
  dashboard) uses to learn about changes made by the worker (a separate
  process, only sharing Redis)
- New `GET /api/v1/tasks/events` endpoint streams that channel to the
  browser as Server-Sent Events, with periodic keep-alive comments so the
  connection doesn't look dead to proxies while idle
- The dashboard replaced its 1.5s polling loop with a single persistent
  `EventSource` connection: one initial `GET /tasks` for the starting
  snapshot, then every update after that arrives pushed, not fetched — a
  "live" / "connecting…" indicator shows the connection state
- Horizontally scales the same way the rest of the system does: every API
  replica subscribes to the same channel independently, so it doesn't
  matter which worker made the change or which API instance a given
  browser is connected to

## Phase 4 (current): Rate limiting + circuit breaker

No real external API to protect yet (that's Phase 5), so a `flaky` task type
simulates one — an unreliable, rate-limited service the worker calls.

- **Token bucket rate limiter**: a single atomic Redis Lua script (capacity 3,
  refills 0.5/s by default) shared across every worker replica — no
  app-level locking needed, since the whole read-refill-consume cycle runs
  server-side in one round trip
- **Circuit breaker**: `CLOSED` → `OPEN` (after 3 consecutive failures,
  short-circuits calls immediately for a 10s cooldown, protecting a
  struggling service from being hammered further) → `HALF_OPEN` (cooldown
  elapsed, exactly one probe call let through) → back to `CLOSED` on
  success or `OPEN` again on failure. Also Redis-backed via atomic Lua
  scripts, so every worker replica agrees on the state and only one probe
  is ever in flight at a time
- Both mechanisms reuse Phase 2's retry/backoff/DLQ machinery rather than
  inventing new plumbing: a rate-limited or breaker-rejected call just
  raises a normal exception, which the worker already knows how to retry
  with backoff or eventually dead-letter
- New `GET /api/v1/status` endpoint + a dashboard status widget show live
  breaker state and token count — pick `flaky` from the task-type dropdown
  (with a configurable simulated fail rate) to trigger and watch both live

## Roadmap

- **Phase 5** — Replace the `sleep` handler with real LLM-backed text summarization / PDF extraction

## Running locally

### Backend

```bash
uv sync
uv run uvicorn taskloom.api.main:app --reload
```

In another terminal, start a worker:

```bash
uv run python -m taskloom.worker.main
```

Requires Redis running locally (`redis-server`, or `docker run -p 6379:6379 redis:7-alpine`).

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

### Everything via Docker Compose

```bash
docker compose up --build
```

- API: http://localhost:8000 (docs at `/docs`)
- Dashboard: http://localhost:5173

Scale workers horizontally:

```bash
docker compose up --scale worker=3
```

### Tests

```bash
uv run pytest
```

# Taskloom

A distributed, asynchronous task-processing system: a FastAPI service accepts
tasks and hands them to Redis-backed queues; independent worker processes
pull from those queues and execute tasks without ever blocking the API.
A React dashboard lets you submit tasks and watch them move through their
lifecycle in real time.

Built iteratively, phase by phase — starting from the simplest possible task
type (a "sleep" task that just waits N seconds) to prove out the plumbing,
then layering on production concerns one at a time.

## Phase 1 (current): Core pipeline

- FastAPI API: create/list/get tasks, health check
- Redis-backed queue (plain Redis lists/hashes — no Celery)
- Async worker(s) executing a `sleep` task type
- Task lifecycle: `PENDING` → `ACTIVE` → `COMPLETED` / `FAILED`
- React + Vite + Tailwind dashboard (polling-based live view)
- Docker Compose orchestration

## Roadmap

- **Phase 2** — Retry logic with backoff + dead-letter queue for permanently failed tasks
- **Phase 3** — Server-Sent Events push endpoint; dashboard upgraded from polling to live push
- **Phase 4** — Distributed rate limiting (token bucket) + circuit breaker for external API calls
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

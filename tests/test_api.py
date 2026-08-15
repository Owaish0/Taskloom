import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from taskloom.api.main import app
from taskloom.models import TaskStatus
from taskloom.queue import set_status


@pytest.fixture
async def fake_redis():
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


@pytest.fixture
async def client(monkeypatch, fake_redis):
    monkeypatch.setattr("taskloom.api.main.get_redis", lambda: fake_redis)
    monkeypatch.setattr("taskloom.api.main.close_redis", lambda: fake_redis.aclose())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac


async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_sleep_task(client):
    resp = await client.post("/api/v1/tasks", json={"type": "sleep", "payload": {"duration": 2}})
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "sleep"
    assert body["status"] == "pending"
    assert body["payload"] == {"duration": 2}


async def test_create_task_rejects_unsupported_type(client):
    resp = await client.post("/api/v1/tasks", json={"type": "bogus", "payload": {}})
    assert resp.status_code == 422


async def test_create_sleep_task_requires_positive_duration(client):
    resp = await client.post("/api/v1/tasks", json={"type": "sleep", "payload": {"duration": -1}})
    assert resp.status_code == 422


async def test_get_task_not_found(client):
    resp = await client.get("/api/v1/tasks/does-not-exist")
    assert resp.status_code == 404


async def test_get_task_roundtrip(client):
    create_resp = await client.post(
        "/api/v1/tasks", json={"type": "sleep", "payload": {"duration": 1}}
    )
    task_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == task_id


async def test_list_tasks(client):
    await client.post("/api/v1/tasks", json={"type": "sleep", "payload": {"duration": 1}})
    await client.post("/api/v1/tasks", json={"type": "sleep", "payload": {"duration": 2}})

    resp = await client.get("/api/v1/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_create_fail_task(client):
    resp = await client.post("/api/v1/tasks", json={"type": "fail", "payload": {}})
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"


async def test_retry_dead_task(client, fake_redis):
    create_resp = await client.post("/api/v1/tasks", json={"type": "fail", "payload": {}})
    task_id = create_resp.json()["id"]
    await set_status(fake_redis, task_id, TaskStatus.FAILED, error="dead", attempts=3)

    resp = await client.post(f"/api/v1/tasks/{task_id}/retry")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["attempts"] == 0


async def test_retry_missing_task_returns_404(client):
    resp = await client.post("/api/v1/tasks/does-not-exist/retry")
    assert resp.status_code == 404


async def test_retry_non_failed_task_returns_409(client):
    create_resp = await client.post(
        "/api/v1/tasks", json={"type": "sleep", "payload": {"duration": 1}}
    )
    task_id = create_resp.json()["id"]  # still PENDING

    resp = await client.post(f"/api/v1/tasks/{task_id}/retry")

    assert resp.status_code == 409

# Note: the SSE endpoint (/api/v1/tasks/events) isn't tested through the HTTP
# client here — httpx's ASGITransport fully drains the app's response before
# returning anything, so it can't exercise a genuinely infinite stream. The
# underlying generator (sse_task_events) is tested directly in test_queue.py
# instead, and the route itself is verified live against the real Docker stack.

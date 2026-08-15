import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from taskloom.api.main import app


@pytest.fixture
async def client(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("taskloom.api.main.get_redis", lambda: fake)
    monkeypatch.setattr("taskloom.api.main.close_redis", lambda: fake.aclose())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await fake.aclose()


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

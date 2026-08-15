import fakeredis.aioredis
import pytest

from taskloom.models import TaskStatus
from taskloom.queue import create_task, dequeue, get_task, list_tasks, set_status


@pytest.fixture
async def redis():
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


async def test_create_and_get_task(redis):
    record = await create_task(redis, "sleep", {"duration": 2})
    assert record.status == TaskStatus.PENDING

    fetched = await get_task(redis, record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.payload == {"duration": 2}


async def test_get_missing_task_returns_none(redis):
    assert await get_task(redis, "does-not-exist") is None


async def test_dequeue_returns_enqueued_id(redis):
    record = await create_task(redis, "sleep", {"duration": 1})
    task_id = await dequeue(redis, timeout=1)
    assert task_id == record.id


async def test_dequeue_times_out_when_empty(redis):
    task_id = await dequeue(redis, timeout=1)
    assert task_id is None


async def test_set_status_updates_result(redis):
    record = await create_task(redis, "sleep", {"duration": 1})
    await set_status(redis, record.id, TaskStatus.COMPLETED, result={"slept_for": 1})

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.COMPLETED
    assert fetched.result == {"slept_for": 1}


async def test_list_tasks_filters_by_status(redis):
    a = await create_task(redis, "sleep", {"duration": 1})
    b = await create_task(redis, "sleep", {"duration": 2})
    await set_status(redis, a.id, TaskStatus.COMPLETED, result={"slept_for": 1})

    completed = await list_tasks(redis, status=TaskStatus.COMPLETED)
    pending = await list_tasks(redis, status=TaskStatus.PENDING)

    assert [t.id for t in completed] == [a.id]
    assert [t.id for t in pending] == [b.id]


async def test_list_tasks_respects_limit_and_offset(redis):
    for i in range(5):
        await create_task(redis, "sleep", {"duration": i + 1})

    page1 = await list_tasks(redis, limit=2, offset=0)
    page2 = await list_tasks(redis, limit=2, offset=2)

    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0].id != page2[0].id

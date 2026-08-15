import asyncio
import json
import time

import fakeredis.aioredis
import pytest

from taskloom.models import TaskStatus
from taskloom.queue import (
    RETRY_QUEUE,
    TASK_EVENTS_CHANNEL,
    TaskNotRetryableError,
    create_task,
    dequeue,
    get_task,
    list_tasks,
    promote_ready_retries,
    retry_task,
    schedule_retry,
    set_status,
    sse_task_events,
)


async def _read_one(pubsub, timeout=2.0):
    async def _loop():
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                return json.loads(message["data"])

    return await asyncio.wait_for(_loop(), timeout=timeout)


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


async def test_create_task_uses_configured_max_attempts(redis):
    record = await create_task(redis, "sleep", {"duration": 1}, max_attempts=5)
    assert record.max_attempts == 5


async def test_schedule_retry_marks_retry_scheduled_and_parks_in_retry_queue(redis):
    record = await create_task(redis, "fail", {})
    await schedule_retry(redis, record.id, attempts=1, delay_seconds=30, error="boom")

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.RETRY_SCHEDULED
    assert fetched.attempts == 1
    assert fetched.error == "boom"

    score = await redis.zscore(RETRY_QUEUE, record.id)
    assert score is not None
    assert score > time.time()  # scheduled in the future


async def test_promote_ready_retries_only_promotes_elapsed_ones(redis):
    ready = await create_task(redis, "fail", {})
    not_ready = await create_task(redis, "fail", {})
    await schedule_retry(redis, ready.id, attempts=1, delay_seconds=-1, error="boom")  # already due
    await schedule_retry(redis, not_ready.id, attempts=1, delay_seconds=60, error="boom")

    promoted = await promote_ready_retries(redis)

    assert promoted == 1
    ready_task = await get_task(redis, ready.id)
    not_ready_task = await get_task(redis, not_ready.id)
    assert ready_task.status == TaskStatus.PENDING
    assert not_ready_task.status == TaskStatus.RETRY_SCHEDULED
    assert await dequeue(redis, timeout=1) == ready.id


async def test_promote_ready_retries_does_not_double_promote(redis):
    record = await create_task(redis, "fail", {})
    await schedule_retry(redis, record.id, attempts=1, delay_seconds=-1, error="boom")

    first = await promote_ready_retries(redis)
    second = await promote_ready_retries(redis)

    assert first == 1
    assert second == 0


async def test_retry_task_resets_failed_task(redis):
    record = await create_task(redis, "fail", {})
    await set_status(redis, record.id, TaskStatus.FAILED, error="permanently dead", attempts=3)

    retried = await retry_task(redis, record.id)

    assert retried.status == TaskStatus.PENDING
    assert retried.attempts == 0
    assert retried.error is None
    assert await dequeue(redis, timeout=1) == record.id


async def test_retry_task_returns_none_for_missing_task(redis):
    assert await retry_task(redis, "does-not-exist") is None


async def test_retry_task_rejects_non_failed_task(redis):
    record = await create_task(redis, "sleep", {"duration": 1})  # still PENDING
    with pytest.raises(TaskNotRetryableError):
        await retry_task(redis, record.id)


async def test_create_task_publishes_event(redis):
    pubsub = redis.pubsub()
    await pubsub.subscribe(TASK_EVENTS_CHANNEL)

    record = await create_task(redis, "sleep", {"duration": 1})
    event = await _read_one(pubsub)

    assert event["id"] == record.id
    assert event["status"] == "pending"

    await pubsub.unsubscribe(TASK_EVENTS_CHANNEL)
    await pubsub.aclose()


async def test_set_status_publishes_event_with_full_record(redis):
    record = await create_task(redis, "sleep", {"duration": 1})
    pubsub = redis.pubsub()
    await pubsub.subscribe(TASK_EVENTS_CHANNEL)

    await set_status(redis, record.id, TaskStatus.COMPLETED, result={"slept_for": 1})
    event = await _read_one(pubsub)

    assert event["id"] == record.id
    assert event["status"] == "completed"
    assert event["result"] == {"slept_for": 1}

    await pubsub.unsubscribe(TASK_EVENTS_CHANNEL)
    await pubsub.aclose()


async def test_promote_ready_retries_publishes_event(redis):
    record = await create_task(redis, "fail", {})
    await schedule_retry(redis, record.id, attempts=1, delay_seconds=-1, error="boom")
    pubsub = redis.pubsub()
    await pubsub.subscribe(TASK_EVENTS_CHANNEL)

    await promote_ready_retries(redis)
    event = await _read_one(pubsub)

    assert event["id"] == record.id
    assert event["status"] == "pending"

    await pubsub.unsubscribe(TASK_EVENTS_CHANNEL)
    await pubsub.aclose()


async def test_retry_task_publishes_event(redis):
    record = await create_task(redis, "fail", {})
    await set_status(redis, record.id, TaskStatus.FAILED, error="dead", attempts=3)
    pubsub = redis.pubsub()
    await pubsub.subscribe(TASK_EVENTS_CHANNEL)

    await retry_task(redis, record.id)
    event = await _read_one(pubsub)

    assert event["id"] == record.id
    assert event["status"] == "pending"
    assert event["attempts"] == 0

    await pubsub.unsubscribe(TASK_EVENTS_CHANNEL)
    await pubsub.aclose()


async def test_sse_task_events_yields_published_task(redis):
    # poll_timeout is short so a keep-alive may legitimately interleave before
    # the data chunk arrives, depending on scheduling — same as a real SSE
    # client, we skip keep-alives and wait for the actual event.
    gen = sse_task_events(redis, poll_timeout=0.5)

    async def first_data_chunk():
        async for chunk in gen:
            if chunk.startswith("data: "):
                return chunk

    reader = asyncio.create_task(first_data_chunk())
    await asyncio.sleep(0.1)  # let the generator reach pubsub.subscribe() first
    record = await create_task(redis, "sleep", {"duration": 1})

    chunk = await asyncio.wait_for(reader, timeout=3)

    event = json.loads(chunk[len("data: ") :].strip())
    assert event["id"] == record.id
    assert event["status"] == "pending"
    await gen.aclose()


async def test_sse_task_events_yields_keepalive_when_idle(redis):
    gen = sse_task_events(redis, poll_timeout=0.05)
    chunk = await asyncio.wait_for(gen.__anext__(), timeout=2)
    assert chunk == ": keep-alive\n\n"
    await gen.aclose()


async def test_sse_task_events_stops_when_disconnected(redis):
    async def already_disconnected():
        return True

    gen = sse_task_events(redis, is_disconnected=already_disconnected)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=2)

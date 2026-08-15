import fakeredis.aioredis
import pytest

from taskloom.models import TaskStatus
from taskloom.queue import create_task, get_task, promote_ready_retries
from taskloom.worker.handlers import HANDLERS
from taskloom.worker.main import process_task


@pytest.fixture
async def redis():
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


@pytest.fixture
def always_fails(monkeypatch):
    """Registers a handler that always raises, and cleans it up afterward."""

    async def handler(payload):
        raise RuntimeError("simulated failure")

    monkeypatch.setitem(HANDLERS, "always_fail", handler)
    return "always_fail"


async def test_failed_task_is_scheduled_for_retry_before_exhausting_attempts(redis, always_fails):
    record = await create_task(redis, always_fails, {}, max_attempts=3)

    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.RETRY_SCHEDULED
    assert fetched.attempts == 1


async def test_task_moves_to_dead_letter_queue_after_exhausting_attempts(
    redis, always_fails, monkeypatch
):
    # Zero out backoff so the retry is immediately "ready" for promote_ready_retries()
    # below, instead of the test having to sleep through real exponential delays.
    monkeypatch.setattr("taskloom.worker.main.settings.retry_backoff_base", 0.0)

    record = await create_task(redis, always_fails, {}, max_attempts=3)

    # Attempt 1: fails, retry scheduled.
    await process_task(redis, record.id)
    # Promote it back to pending (simulating the backoff delay having elapsed).
    await promote_ready_retries(redis)
    # Attempt 2: fails again, retry scheduled.
    await process_task(redis, record.id)
    await promote_ready_retries(redis)
    # Attempt 3: this was the last allowed attempt — dead-letter queue.
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.FAILED
    assert fetched.attempts == 3
    assert fetched.error == "simulated failure"


async def test_successful_task_completes_normally(redis):
    record = await create_task(redis, "sleep", {"duration": 0})

    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.COMPLETED
    assert fetched.result == {"slept_for": 0.0}


async def test_unknown_task_type_fails_immediately_without_retry(redis):
    record = await create_task(redis, "not-a-real-type", {}, max_attempts=3)

    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.FAILED
    assert fetched.attempts == 0  # never actually "attempted" — no handler to run

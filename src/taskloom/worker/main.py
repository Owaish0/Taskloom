from __future__ import annotations

import asyncio
import logging

from taskloom.config import settings
from taskloom.models import TaskStatus
from taskloom.queue import dequeue, get_task, promote_ready_retries, schedule_retry, set_status
from taskloom.redis_client import close_redis, get_redis
from taskloom.worker.handlers import HANDLERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
logger = logging.getLogger("taskloom.worker")


async def process_task(redis, task_id: str) -> None:
    record = await get_task(redis, task_id)
    if record is None:
        logger.warning("task %s not found, skipping", task_id)
        return

    handler = HANDLERS.get(record.type)
    if handler is None:
        # Not a retryable condition — no version of retrying will make an
        # unknown task type known. Straight to the dead-letter queue.
        await set_status(redis, task_id, TaskStatus.FAILED, error=f"Unknown task type: {record.type}")
        return

    await set_status(redis, task_id, TaskStatus.ACTIVE)
    logger.info("processing task %s (type=%s, attempt %s/%s)", task_id, record.type, record.attempts + 1, record.max_attempts)
    try:
        result = await handler(redis, record.payload)
    except Exception as exc:
        attempts = record.attempts + 1
        if attempts < record.max_attempts:
            delay = settings.retry_backoff_base * (2 ** (attempts - 1))
            logger.warning(
                "task %s failed (attempt %s/%s): %s — retrying in %.0fs",
                task_id, attempts, record.max_attempts, exc, delay,
            )
            await schedule_retry(redis, task_id, attempts=attempts, delay_seconds=delay, error=str(exc))
        else:
            logger.error(
                "task %s failed permanently after %s attempts: %s — moved to dead-letter queue",
                task_id, attempts, exc,
            )
            await set_status(redis, task_id, TaskStatus.FAILED, error=str(exc), attempts=attempts)
    else:
        # Clear any error left over from an earlier failed attempt — a task
        # that failed once and then succeeded on retry should read as
        # cleanly COMPLETED, not still show the stale error message.
        await set_status(redis, task_id, TaskStatus.COMPLETED, result=result, error="")
        logger.info("task %s completed", task_id)


async def consume_loop(redis) -> None:
    while True:
        task_id = await dequeue(redis, timeout=settings.worker_poll_timeout)
        if task_id is None:
            continue
        await process_task(redis, task_id)


async def retry_promoter_loop(redis) -> None:
    """Runs alongside the main consume loop: periodically checks the retry
    queue for tasks whose backoff delay has elapsed and moves them back onto
    the pending queue so a worker will pick them up again. Safe to run in
    every worker replica — promote_ready_retries() is race-safe."""
    while True:
        try:
            promoted = await promote_ready_retries(redis)
            if promoted:
                logger.info("promoted %s retry-scheduled task(s) back to pending", promoted)
        except Exception:
            logger.exception("retry promoter iteration failed")
        await asyncio.sleep(settings.retry_poll_interval)


async def run() -> None:
    redis = get_redis()
    logger.info("worker started, polling %s", settings.redis_url)
    try:
        await asyncio.gather(consume_loop(redis), retry_promoter_loop(redis))
    finally:
        await close_redis()


if __name__ == "__main__":
    asyncio.run(run())

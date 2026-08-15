from __future__ import annotations

import asyncio
import logging

from taskloom.config import settings
from taskloom.models import TaskStatus
from taskloom.queue import dequeue, get_task, set_status
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
        await set_status(redis, task_id, TaskStatus.FAILED, error=f"Unknown task type: {record.type}")
        return

    await set_status(redis, task_id, TaskStatus.ACTIVE)
    logger.info("processing task %s (type=%s)", task_id, record.type)
    try:
        result = await handler(record.payload)
    except Exception as exc:
        logger.exception("task %s failed", task_id)
        await set_status(redis, task_id, TaskStatus.FAILED, error=str(exc))
    else:
        await set_status(redis, task_id, TaskStatus.COMPLETED, result=result)
        logger.info("task %s completed", task_id)


async def run() -> None:
    redis = get_redis()
    logger.info("worker started, polling %s", settings.redis_url)
    try:
        while True:
            task_id = await dequeue(redis, timeout=settings.worker_poll_timeout)
            if task_id is None:
                continue
            await process_task(redis, task_id)
    finally:
        await close_redis()


if __name__ == "__main__":
    asyncio.run(run())

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from taskloom.config import settings
from taskloom.models import TaskRecord, TaskStatus

PENDING_QUEUE = "queue:pending"
RETRY_QUEUE = "queue:retry"  # sorted set: score = unix ts when the retry becomes ready
TASK_INDEX = "tasks:index"


class TaskNotRetryableError(Exception):
    """Raised when a manual retry is requested for a task that isn't in the DLQ."""


def _task_key(task_id: str) -> str:
    return f"task:{task_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(record: TaskRecord) -> dict[str, str]:
    return {
        "id": record.id,
        "type": record.type,
        "status": record.status.value,
        "payload": json.dumps(record.payload),
        "result": json.dumps(record.result) if record.result is not None else "",
        "error": record.error or "",
        "attempts": str(record.attempts),
        "max_attempts": str(record.max_attempts),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _decode(data: dict[str, str]) -> TaskRecord:
    return TaskRecord(
        id=data["id"],
        type=data["type"],
        status=TaskStatus(data["status"]),
        payload=json.loads(data["payload"]) if data.get("payload") else {},
        result=json.loads(data["result"]) if data.get("result") else None,
        error=data.get("error") or None,
        attempts=int(data.get("attempts", 0)),
        max_attempts=int(data.get("max_attempts", 1)),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


async def create_task(
    redis: Redis,
    task_type: str,
    payload: dict[str, Any],
    max_attempts: int | None = None,
) -> TaskRecord:
    now = _now()
    record = TaskRecord(
        id=str(uuid.uuid4()),
        type=task_type,
        status=TaskStatus.PENDING,
        payload=payload,
        max_attempts=max_attempts if max_attempts is not None else settings.default_max_attempts,
        created_at=now,
        updated_at=now,
    )
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(_task_key(record.id), mapping=_encode(record))
        pipe.zadd(TASK_INDEX, {record.id: time.time()})
        pipe.rpush(PENDING_QUEUE, record.id)
        await pipe.execute()
    return record


async def get_task(redis: Redis, task_id: str) -> TaskRecord | None:
    data = await redis.hgetall(_task_key(task_id))
    if not data:
        return None
    return _decode(data)


async def list_tasks(
    redis: Redis,
    status: TaskStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TaskRecord]:
    ids = await redis.zrevrange(TASK_INDEX, 0, -1)
    tasks: list[TaskRecord] = []
    for task_id in ids:
        record = await get_task(redis, task_id)
        if record is None:
            continue
        if status is not None and record.status != status:
            continue
        tasks.append(record)
    return tasks[offset : offset + limit]


async def set_status(
    redis: Redis,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    attempts: int | None = None,
) -> None:
    fields: dict[str, str] = {"status": status.value, "updated_at": _now()}
    if result is not None:
        fields["result"] = json.dumps(result)
    if error is not None:
        fields["error"] = error
    if attempts is not None:
        fields["attempts"] = str(attempts)
    await redis.hset(_task_key(task_id), mapping=fields)


async def dequeue(redis: Redis, timeout: int) -> str | None:
    item = await redis.blpop([PENDING_QUEUE], timeout=timeout)
    if item is None:
        return None
    _, task_id = item
    return task_id


async def schedule_retry(
    redis: Redis,
    task_id: str,
    attempts: int,
    delay_seconds: float,
    error: str,
) -> None:
    """Record a failed attempt and park the task in the retry queue until
    ``delay_seconds`` from now, instead of requeuing it immediately."""
    await set_status(
        redis, task_id, TaskStatus.RETRY_SCHEDULED, error=error, attempts=attempts
    )
    await redis.zadd(RETRY_QUEUE, {task_id: time.time() + delay_seconds})


async def promote_ready_retries(redis: Redis) -> int:
    """Move any retry-queue tasks whose delay has elapsed back onto the
    pending queue. Safe to call from multiple worker processes concurrently:
    ZREM only succeeds for whichever caller removes the entry first, so a
    task is never promoted twice."""
    ready_ids = await redis.zrangebyscore(RETRY_QUEUE, min=0, max=time.time())
    promoted = 0
    for task_id in ready_ids:
        removed = await redis.zrem(RETRY_QUEUE, task_id)
        if not removed:
            continue  # another worker already claimed this one
        await redis.hset(
            _task_key(task_id),
            mapping={"status": TaskStatus.PENDING.value, "updated_at": _now()},
        )
        await redis.rpush(PENDING_QUEUE, task_id)
        promoted += 1
    return promoted


async def retry_task(redis: Redis, task_id: str) -> TaskRecord | None:
    """Manually requeue a dead-lettered (FAILED) task, resetting its attempt
    count. Returns None if the task doesn't exist. Raises
    TaskNotRetryableError if it exists but isn't currently FAILED."""
    record = await get_task(redis, task_id)
    if record is None:
        return None
    if record.status != TaskStatus.FAILED:
        raise TaskNotRetryableError(
            f"Task {task_id} is {record.status.value}, not failed — nothing to retry"
        )
    await redis.hset(
        _task_key(task_id),
        mapping={
            "status": TaskStatus.PENDING.value,
            "attempts": "0",
            "error": "",
            "updated_at": _now(),
        },
    )
    await redis.rpush(PENDING_QUEUE, task_id)
    updated = await get_task(redis, task_id)
    assert updated is not None
    return updated

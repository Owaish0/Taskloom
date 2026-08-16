from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from taskloom.config import settings
from taskloom.models import TaskCreate, TaskRecord, TaskStatus
from taskloom.queue import (
    TaskNotRetryableError,
    create_task,
    get_task,
    list_tasks,
    retry_task,
    sse_task_events,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])

SUPPORTED_TASK_TYPES = {"sleep", "fail", "flaky", "summarize"}


@router.post("/tasks", response_model=TaskRecord, status_code=201)
async def submit_task(task: TaskCreate, request: Request) -> TaskRecord:
    if task.type not in SUPPORTED_TASK_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported task type: {task.type!r}")

    if task.type == "sleep":
        duration = task.payload.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise HTTPException(
                status_code=422, detail="payload.duration must be a positive number"
            )

    if task.type == "flaky" and "fail_rate" in task.payload:
        fail_rate = task.payload["fail_rate"]
        if not isinstance(fail_rate, (int, float)) or not 0 <= fail_rate <= 1:
            raise HTTPException(
                status_code=422, detail="payload.fail_rate must be a number between 0 and 1"
            )

    if task.type == "summarize":
        text = task.payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="payload.text must be a non-empty string")
        if len(text) > settings.summarize_max_input_chars:
            raise HTTPException(
                status_code=422,
                detail=f"payload.text exceeds the {settings.summarize_max_input_chars}-character limit",
            )

    redis = request.app.state.redis
    return await create_task(redis, task.type, task.payload)


@router.get("/tasks/events")
async def task_events(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of task updates. Registered before
    /tasks/{task_id} so "events" isn't swallowed as a task_id — FastAPI
    matches routes in registration order."""
    redis = request.app.state.redis
    return StreamingResponse(
        sse_task_events(redis, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks/{task_id}", response_model=TaskRecord)
async def read_task(task_id: str, request: Request) -> TaskRecord:
    redis = request.app.state.redis
    record = await get_task(redis, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return record


@router.post("/tasks/{task_id}/retry", response_model=TaskRecord)
async def retry_dead_task(task_id: str, request: Request) -> TaskRecord:
    """Manually requeue a task that exhausted its retries and landed in the
    dead-letter queue (status FAILED), resetting its attempt count."""
    redis = request.app.state.redis
    try:
        record = await retry_task(redis, task_id)
    except TaskNotRetryableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return record


@router.get("/tasks", response_model=list[TaskRecord])
async def read_tasks(
    request: Request,
    status: TaskStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TaskRecord]:
    redis = request.app.state.redis
    return await list_tasks(redis, status=status, limit=limit, offset=offset)


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    redis = request.app.state.redis
    try:
        await redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    return {"status": "ok"}

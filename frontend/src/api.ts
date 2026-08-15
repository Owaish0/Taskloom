import type { TaskRecord } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function createSleepTask(duration: number): Promise<TaskRecord> {
  const res = await fetch(`${API_URL}/api/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "sleep", payload: { duration } }),
  });
  return handleResponse<TaskRecord>(res);
}

export async function createFailingTask(): Promise<TaskRecord> {
  const res = await fetch(`${API_URL}/api/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "fail", payload: {} }),
  });
  return handleResponse<TaskRecord>(res);
}

export async function listTasks(): Promise<TaskRecord[]> {
  const res = await fetch(`${API_URL}/api/v1/tasks?limit=50`);
  return handleResponse<TaskRecord[]>(res);
}

export async function retryTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(`${API_URL}/api/v1/tasks/${taskId}/retry`, { method: "POST" });
  return handleResponse<TaskRecord>(res);
}

export function taskEventsUrl(): string {
  return `${API_URL}/api/v1/tasks/events`;
}

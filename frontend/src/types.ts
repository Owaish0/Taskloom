export type TaskStatus = "pending" | "active" | "completed" | "retry_scheduled" | "failed";

export interface TaskRecord {
  id: string;
  type: string;
  status: TaskStatus;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
}

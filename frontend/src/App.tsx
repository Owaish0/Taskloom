import { useCallback, useEffect, useState } from "react";
import { listTasks, retryTask, taskEventsUrl } from "./api";
import NewTaskForm from "./components/NewTaskForm";
import TaskTable from "./components/TaskTable";
import type { TaskRecord } from "./types";

function upsertTask(tasks: TaskRecord[], updated: TaskRecord): TaskRecord[] {
  const idx = tasks.findIndex((t) => t.id === updated.id);
  if (idx === -1) {
    // A brand-new task is, by construction, the newest — put it up top to
    // match the initial GET /tasks ordering (newest first) without re-sorting.
    return [updated, ...tasks];
  }
  const next = [...tasks];
  next[idx] = updated;
  return next;
}

export default function App() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    // One-time snapshot to populate the table — the SSE stream only carries
    // changes going forward, not history.
    listTasks()
      .then(setTasks)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const source = new EventSource(taskEventsUrl());
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    source.onmessage = (event) => {
      const updated: TaskRecord = JSON.parse(event.data);
      setTasks((prev) => upsertTask(prev, updated));
    };
    return () => source.close();
  }, []);

  const handleRetry = useCallback((taskId: string) => {
    // No local state update needed here — the worker picking this back up
    // and every status change along the way arrives via the SSE stream.
    retryTask(taskId).catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold text-slate-900">Taskloom</h1>
          <span
            className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              live ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-600"
            }`}
            title={live ? "Live updates connected" : "Reconnecting…"}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${live ? "bg-emerald-500" : "bg-slate-400"}`}
            />
            {live ? "live" : "connecting…"}
          </span>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Submit a task and watch it move through the queue in real time — failed tasks
          retry with backoff before landing in the dead-letter queue.
        </p>

        <div className="mt-6">
          <NewTaskForm />
        </div>

        <TaskTable tasks={tasks} onRetry={handleRetry} />
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { listTasks } from "./api";
import NewTaskForm from "./components/NewTaskForm";
import TaskTable from "./components/TaskTable";
import type { TaskRecord } from "./types";

const POLL_INTERVAL_MS = 1500;

export default function App() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);

  const refresh = useCallback(() => {
    listTasks()
      .then(setTasks)
      .catch(() => {
        // transient errors are fine to swallow — next poll will retry
      });
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-semibold text-slate-900">Taskloom</h1>
        <p className="mt-1 text-sm text-slate-500">
          Submit a sleep task and watch it move through the queue.
        </p>

        <div className="mt-6">
          <NewTaskForm onCreated={refresh} />
        </div>

        <TaskTable tasks={tasks} />
      </div>
    </div>
  );
}

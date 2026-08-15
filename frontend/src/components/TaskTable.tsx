import type { TaskRecord, TaskStatus } from "../types";

const STATUS_STYLES: Record<TaskStatus, string> = {
  pending: "bg-amber-100 text-amber-800",
  active: "bg-blue-100 text-blue-800",
  completed: "bg-emerald-100 text-emerald-800",
  retry_scheduled: "bg-orange-100 text-orange-800",
  failed: "bg-red-100 text-red-800",
};

interface Props {
  tasks: TaskRecord[];
  onRetry: (taskId: string) => void;
}

export default function TaskTable({ tasks, onRetry }: Props) {
  if (tasks.length === 0) {
    return <p className="mt-6 text-sm text-slate-500">No tasks yet — submit one above.</p>;
  }

  return (
    <div className="mt-6 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">ID</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Attempts</th>
            <th className="px-4 py-2 font-medium">Payload</th>
            <th className="px-4 py-2 font-medium">Result / Error</th>
            <th className="px-4 py-2 font-medium">Updated</th>
            <th className="px-4 py-2 font-medium"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {tasks.map((task) => (
            <tr key={task.id}>
              <td className="px-4 py-2 font-mono text-xs text-slate-600">
                {task.id.slice(0, 8)}
              </td>
              <td className="px-4 py-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[task.status]}`}
                >
                  {task.status}
                </span>
              </td>
              <td className="px-4 py-2 text-slate-600">
                {task.attempts}/{task.max_attempts}
              </td>
              <td className="px-4 py-2 text-slate-600">{JSON.stringify(task.payload)}</td>
              <td className="px-4 py-2 text-slate-600">
                {task.error ?? (task.result ? JSON.stringify(task.result) : "—")}
              </td>
              <td className="px-4 py-2 text-slate-500">
                {new Date(task.updated_at).toLocaleTimeString()}
              </td>
              <td className="px-4 py-2">
                {task.status === "failed" && (
                  <button
                    onClick={() => onRetry(task.id)}
                    className="rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  >
                    Retry
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

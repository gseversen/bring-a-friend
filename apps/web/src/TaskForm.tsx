import { useState, type FormEvent } from "react";
import { postToAgent } from "./api";

interface Props {
  room: string;
  userName: string;
  // True while the room's run is unfinished (running, paused, awaiting approval…).
  busy: boolean;
}

export function TaskForm({ room, userName, busy }: Props) {
  const [task, setTask] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    // Only starts the run. Progress comes back through the shared doc, so
    // every client (not just this one) sees it.
    const err = await postToAgent("/runs", { room, task, startedBy: userName });
    setSubmitting(false);
    if (err) setError(err);
    else setTask("");
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="Give the agent a research topic, e.g. the history of solar power"
          className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!task.trim() || busy || submitting}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Run in progress" : "Start task"}
        </button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </form>
  );
}

import type { RunStatus } from "@baf/doc-schema";
import { getIdentity } from "./identity";
import { useRoom } from "./useRoom";
import { Presence } from "./Presence";
import { RunControls } from "./RunControls";
import { TaskForm } from "./TaskForm";
import { Timeline } from "./Timeline";

// Rooms are chosen by URL (?room=name) until there is real session management.
const room = new URLSearchParams(window.location.search).get("room") || "demo";
const FINISHED: RunStatus[] = ["idle", "done", "error"];
// Created once per page load so useRoom's effect doesn't reconnect on every render.
const me = getIdentity();

export default function App() {
  const { status, run, timeline, peers } = useRoom(room, me);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <header className="flex items-baseline gap-3">
        <h1 className="text-xl font-semibold text-slate-900">bring-a-friend</h1>
        <span className="text-sm text-slate-500">room: {room}</span>
        <span className={`ml-auto text-xs ${status === "connected" ? "text-emerald-600" : "text-amber-600"}`}>{status}</span>
      </header>
      <div className="grid gap-6 md:grid-cols-[1fr_14rem]">
        <main className="flex flex-col gap-6">
          <TaskForm room={room} userName={me.name} busy={!!run.status && !FINISHED.includes(run.status)} />
          <RunControls run={run} userName={me.name} />
          <Timeline run={run} events={timeline} />
        </main>
        <aside className="rounded-md border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">In this room</h2>
          <Presence peers={peers} agentStatus={run.status} />
        </aside>
      </div>
    </div>
  );
}

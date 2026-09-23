import type { RunStatus } from "@baf/doc-schema";
import type { Peer } from "./useRoom";

interface Props {
  peers: Peer[];
  agentStatus: RunStatus | undefined;
}

export function Presence({ peers, agentStatus }: Props) {
  return (
    <ul className="flex flex-col gap-2 text-sm">
      {peers.map((peer) => (
        <li key={peer.clientId} className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: peer.color }} />
          {peer.name}
          {peer.isSelf && <span className="text-slate-400">(you)</span>}
        </li>
      ))}
      {/* The agent is not a Yjs client (see README), so its presence comes from the run status in the doc. */}
      <li className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${agentStatus === "running" ? "animate-pulse bg-slate-900" : "bg-slate-300"}`} />
        Agent
        <span className="text-slate-400">{agentStatus === "running" ? "working" : "idle"}</span>
      </li>
    </ul>
  );
}

import { useEffect, useState } from "react";
import * as Y from "yjs";
import { HocuspocusProvider, WebSocketStatus } from "@hocuspocus/provider";
import { getRun, getTimeline, type PresenceUser, type RunInfo, type TimelineEvent } from "@baf/doc-schema";

export interface Peer extends PresenceUser {
  clientId: number;
  isSelf: boolean;
}

// Joins a room: syncs its Y.Doc over WebSocket and mirrors the parts the UI
// needs into React state.
export function useRoom(roomName: string, user: PresenceUser) {
  const [status, setStatus] = useState<WebSocketStatus>(WebSocketStatus.Connecting);
  const [run, setRun] = useState<Partial<RunInfo>>({});
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [peers, setPeers] = useState<Peer[]>([]);

  useEffect(() => {
    const doc = new Y.Doc();
    const provider = new HocuspocusProvider({
      url: import.meta.env.VITE_SYNC_URL ?? "ws://localhost:1234",
      name: roomName,
      document: doc,
      onStatus: ({ status }) => setStatus(status),
      // Awareness is Yjs' ephemeral channel: each client publishes its own
      // state, and a client's entry disappears when it disconnects.
      onAwarenessChange: ({ states }) =>
        setPeers(
          states
            .filter((s) => s.user)
            .map((s) => ({ ...(s.user as PresenceUser), clientId: s.clientId, isSelf: s.clientId === doc.clientID })),
        ),
    });
    provider.setAwarenessField("user", user);

    // Observers fire for every change, whether it came from this client, a
    // peer, or the agent (via the sync server), including the initial sync.
    const runMap = getRun(doc);
    const events = getTimeline(doc);
    const onRun = () => setRun(runMap.toJSON() as Partial<RunInfo>);
    const onTimeline = () => setTimeline(events.toArray());
    runMap.observe(onRun);
    events.observe(onTimeline);

    return () => {
      runMap.unobserve(onRun);
      events.unobserve(onTimeline);
      provider.destroy();
      doc.destroy();
    };
  }, [roomName, user]);

  return { status, run, timeline, peers };
}

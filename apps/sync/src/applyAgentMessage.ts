import type * as Y from "yjs";
import { getRun, getTimeline, type AgentMessage } from "@baf/doc-schema";

// Applies one agent message to a room's doc. Everything happens in a single
// Yjs transaction, so connected clients receive it as one atomic update.
export function applyAgentMessage(doc: Y.Doc, msg: AgentMessage): void {
  const run = getRun(doc);
  const timeline = getTimeline(doc);

  doc.transact(() => {
    switch (msg.type) {
      case "run_started":
        // One run per room for now: a new run replaces the previous timeline.
        timeline.delete(0, timeline.length);
        for (const [key, value] of Object.entries(msg.run)) run.set(key, value);
        break;
      case "event":
        // Drop late events from a run that has already been replaced.
        if (run.get("id") !== msg.event.runId) return;
        timeline.push([msg.event]);
        break;
      case "run_finished":
        if (run.get("id") !== msg.runId) return;
        run.set("status", msg.status);
        break;
    }
  });
}

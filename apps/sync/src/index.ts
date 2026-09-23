import { Server } from "@hocuspocus/server";
import type { IncomingMessage } from "node:http";
import type { AgentMessage } from "@baf/doc-schema";
import { applyAgentMessage } from "./applyAgentMessage.js";

const port = Number(process.env.SYNC_PORT ?? 1234);

// POST /rooms/:room/messages is how the agent writes into a room.
const MESSAGES_PATH = /^\/rooms\/([^/]+)\/messages$/;

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const server = new Server({
  port,
  // Localhost only: the agent endpoint below has no auth yet (out of scope for M1).
  address: "127.0.0.1",
  // The same HTTP server handles WebSocket upgrades (browsers) and plain
  // HTTP requests (the agent), so the sync server needs only one port.
  async onRequest({ request, response, instance }) {
    const match = request.method === "POST" && request.url?.match(MESSAGES_PATH);
    if (!match) return; // fall through to Hocuspocus' default response

    const room = decodeURIComponent(match[1]);
    let msg: AgentMessage;
    try {
      msg = (await readJson(request)) as AgentMessage;
    } catch {
      response.writeHead(400).end("invalid JSON");
      throw null;
    }

    // A direct connection lets server code edit a document as if it were a
    // client: the change is broadcast to every browser connected to the room.
    const connection = await instance.openDirectConnection(room);
    try {
      await connection.transact((doc) => applyAgentMessage(doc, msg));
    } finally {
      await connection.disconnect();
    }

    response.writeHead(204).end();
    // Hocuspocus convention: throwing null means "request handled, skip the
    // default response".
    throw null;
  },
});

server.listen();

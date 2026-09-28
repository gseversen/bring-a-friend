const AGENT_URL = import.meta.env.VITE_AGENT_URL ?? "http://localhost:8000";

// Sends a request to the agent. Returns null on success, or a message to show
// the user (e.g. the reason for a 409 when someone else acted first).
// Results never come back here: every client sees them through the shared doc.
export async function postToAgent(path: string, body: object): Promise<string | null> {
  try {
    const res = await fetch(`${AGENT_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) return null;
    const data = await res.json().catch(() => null);
    return typeof data?.detail === "string" ? data.detail : `Agent returned ${res.status}`;
  } catch {
    return "Could not reach the agent service.";
  }
}

import type { PresenceUser } from "@baf/doc-schema";

const NAMES = ["Otter", "Falcon", "Maple", "Comet", "Badger", "Juniper", "Heron", "Quartz"];
const COLORS = ["#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899"];
const KEY = "baf-identity";

const pick = <T,>(items: T[]) => items[Math.floor(Math.random() * items.length)];

// sessionStorage rather than localStorage: each tab gets its own identity (so two
// windows show up as two people), but a reload keeps the same name.
export function getIdentity(): PresenceUser {
  const saved = sessionStorage.getItem(KEY);
  if (saved) return JSON.parse(saved);
  const user = { name: `${pick(NAMES)} ${Math.floor(Math.random() * 90) + 10}`, color: pick(COLORS) };
  sessionStorage.setItem(KEY, JSON.stringify(user));
  return user;
}

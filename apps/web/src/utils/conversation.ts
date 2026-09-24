export type OutcomeLabel = "Resolved" | "Follow-up" | "Escalated";

const resolvedValues = new Set(["answered", "completed", "resolved", "success"]);

export function outcomeLabel(resolution: string | null): OutcomeLabel {
  const normalized = resolution?.trim().toLocaleLowerCase() ?? "";
  if (resolvedValues.has(normalized)) return "Resolved";
  if (normalized.includes("escalat")) return "Escalated";
  return "Follow-up";
}

export function conversationTitle(resolution: string | null): string {
  const outcome = outcomeLabel(resolution);
  if (outcome === "Resolved") return "Customer question resolved";
  if (outcome === "Escalated") return "Conversation escalated";
  return "Follow-up requested";
}

export function conversationPreview(summary: string | null): string {
  return summary?.trim() || "No summary was recorded for this conversation.";
}

export function formatDuration(totalSeconds: number | null): string {
  if (totalSeconds === null) return "—";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function formatAverageDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatConversationDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(isoDate));
}

export function formatConversationTime(isoDate: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(isoDate));
}

export function formatWorkspaceDate(date = new Date()): string {
  return new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(date);
}

export function shortConversationId(id: string): string {
  return `#${id.slice(0, 8).toLocaleUpperCase()}`;
}

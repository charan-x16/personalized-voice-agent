import type { VoiceSessionCancelStatus } from "../api-types";

export const CANCEL_MAX_ATTEMPTS = 3;

const terminalCancellationStatuses: ReadonlySet<VoiceSessionCancelStatus> = new Set([
  "cancelled",
  "completed",
  "ended",
  "expired",
  "failed",
]);

export function isTerminalCancellationStatus(status: VoiceSessionCancelStatus): boolean {
  return terminalCancellationStatuses.has(status);
}

export function shouldRetryCancellationResponse(
  httpStatus: number,
  cancellationStatus?: VoiceSessionCancelStatus,
): boolean {
  return (
    httpStatus === 503 ||
    (httpStatus >= 200 && httpStatus < 300 && cancellationStatus === "cancelling")
  );
}

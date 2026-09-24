import type { VoiceSessionResponse } from "@/lib/api-types";

export type VoicePhase =
  | "ready"
  | "requesting"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "ending"
  | "ended"
  | "error";

export type VoiceStopReason =
  | "user"
  | "provider"
  | "error"
  | "reset"
  | "unmount"
  | "pagehide";

export type VoiceTransportEvent =
  | { type: "connected" }
  | { type: "state"; state: "listening" | "thinking" | "speaking" }
  | {
      type: "transcript";
      turnId: string;
      speaker: "customer" | "agent";
      text: string;
      final: boolean;
    }
  | { type: "completed" }
  | { type: "closed"; expected: boolean; reason?: string }
  | { type: "error"; code: string; message: string };

export type VoiceTransportStartOptions = {
  connection: VoiceSessionResponse["connection"];
  microphone: MediaStream | null;
  signal: AbortSignal;
  onEvent: (event: VoiceTransportEvent) => void;
};

export interface VoiceTransport {
  readonly kind: VoiceSessionResponse["connection"]["transport"];
  readonly supportsTextPrompts: boolean;

  start(options: VoiceTransportStartOptions): Promise<void>;
  setInputEnabled(enabled: boolean): void;
  sendText(text: string): boolean;
  stop(reason: VoiceStopReason): Promise<void>;
}

export class VoiceTransportError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "VoiceTransportError";
  }
}

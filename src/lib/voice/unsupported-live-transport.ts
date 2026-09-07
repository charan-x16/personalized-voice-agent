import type { VoiceTransport } from "./contracts";
import { VoiceTransportError } from "./contracts";

export class UnsupportedLiveVoiceTransport implements VoiceTransport {
  readonly kind = "websocket" as const;
  readonly supportsTextPrompts = false;

  async start(): Promise<void> {
    // Do not construct a WebSocket here. Authentication, audio framing, events,
    // and close behavior must come from Sarvam's provisioned contract.
    throw new VoiceTransportError(
      "live_protocol_unavailable",
      "The live Sarvam transport is not enabled for this workspace yet.",
    );
  }

  setInputEnabled(): void {}

  sendText(): boolean {
    return false;
  }

  async stop(): Promise<void> {}
}

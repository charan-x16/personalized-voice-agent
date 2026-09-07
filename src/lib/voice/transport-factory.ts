import type { VoiceSessionResponse } from "@/lib/api-types";

import type { VoiceTransport } from "./contracts";
import { MockVoiceTransport } from "./mock-transport";
import { UnsupportedLiveVoiceTransport } from "./unsupported-live-transport";

type CreateVoiceTransportOptions = {
  session: VoiceSessionResponse;
  mockGreeting: string;
  responseForPrompt: (prompt: string) => string | undefined;
};

export function createVoiceTransport({
  session,
  mockGreeting,
  responseForPrompt,
}: CreateVoiceTransportOptions): VoiceTransport {
  if (session.connection.transport === "mock") {
    return new MockVoiceTransport({
      greeting: mockGreeting,
      responseForPrompt,
    });
  }

  return new UnsupportedLiveVoiceTransport();
}


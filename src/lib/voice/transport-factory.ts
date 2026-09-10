import type { VoiceSessionResponse } from "@/lib/api-types";

import type { VoiceTransport } from "./contracts";
import { voiceTransportRequiresMicrophone } from "./microphone";
import { MockVoiceTransport } from "./mock-transport";
import { WebSocketVoiceTransport } from "./websocket-transport";

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
  if (!voiceTransportRequiresMicrophone(session.connection.transport)) {
    return new MockVoiceTransport({
      greeting: mockGreeting,
      responseForPrompt,
    });
  }

  return new WebSocketVoiceTransport();
}

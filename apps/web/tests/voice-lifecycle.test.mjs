import assert from "node:assert/strict";
import test from "node:test";

import {
  parseCancelVoiceSessionResponse,
  parseVoiceSessionResponse,
} from "../src/lib/api-validation.ts";
import {
  initialVoiceSessionState,
  voiceSessionReducer,
} from "../src/lib/voice/session-reducer.ts";
import {
  boundedRetryAfterMilliseconds,
  parseRetryAfterSeconds,
} from "../src/lib/retry-after.ts";
import {
  CANCEL_MAX_ATTEMPTS,
  isTerminalCancellationStatus,
  shouldRetryCancellationResponse,
} from "../src/lib/voice/cancellation-policy.ts";
import {
  connectionExpiryDelayMilliseconds,
  MAX_CONNECTION_EXPIRY_DELAY_MS,
} from "../src/lib/voice/connection-expiry.ts";
import { WebSocketVoiceTransport } from "../src/lib/voice/websocket-transport.ts";
import {
  acquireMicrophoneForTransport,
  voiceTransportRequiresMicrophone,
} from "../src/lib/voice/microphone.ts";

const now = Date.parse("2026-03-03T10:00:00.000Z");

function futureIso(minutes) {
  return new Date(now + minutes * 60_000).toISOString();
}

function websocketSession(overrides = {}) {
  return {
    session_id: "session-1",
    provider: "sarvam",
    status: "ready",
    language: "English",
    expires_at: futureIso(15),
    connection: {
      transport: "websocket",
      websocket_url: "wss://voice.example.test/connect?ticket=ephemeral",
      expires_at: futureIso(15),
    },
    ...overrides,
  };
}

test("voice reducer follows the mock lifecycle and updates partial transcript turns", () => {
  let state = voiceSessionReducer(initialVoiceSessionState, { type: "start" });
  assert.equal(state.phase, "requesting");

  state = voiceSessionReducer(state, {
    type: "session-created",
    sessionId: "session-1",
    connectionExpiresAt: futureIso(15),
    transport: "mock",
  });
  state = voiceSessionReducer(state, { type: "microphone-ready" });
  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: { type: "connected" },
  });
  assert.equal(state.phase, "listening");

  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: {
      type: "transcript",
      turnId: "turn-1",
      speaker: "agent",
      text: "Hel",
      final: false,
    },
  });
  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: {
      type: "transcript",
      turnId: "turn-1",
      speaker: "agent",
      text: "Hello",
      final: true,
    },
  });

  assert.equal(state.transcript.length, 1);
  assert.deepEqual(state.transcript[0], {
    id: "turn-1",
    speaker: "Svara",
    text: "Hello",
    final: true,
  });

  state = voiceSessionReducer(state, { type: "prompt-sent", prompt: "Help" });
  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: { type: "state", state: "thinking" },
  });
  assert.equal(state.activePrompt, "Help");
  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: { type: "state", state: "listening" },
  });
  assert.equal(state.activePrompt, null);

  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: { type: "completed" },
  });
  assert.equal(state.providerCompleted, true);

  state = voiceSessionReducer(state, { type: "ending" });
  state = voiceSessionReducer(state, { type: "ended" });
  assert.equal(state.phase, "ended");
  assert.equal(state.sessionId, null);
});

test("transport events cannot activate an idle session", () => {
  const state = voiceSessionReducer(initialVoiceSessionState, {
    type: "transport-event",
    event: { type: "connected" },
  });
  assert.deepEqual(state, initialVoiceSessionState);
});

test("live transport is a real websocket adapter and rejects a mismatched contract", async () => {
  const transport = new WebSocketVoiceTransport();
  assert.equal(transport.kind, "websocket");
  assert.equal(transport.supportsTextPrompts, false);
  await assert.rejects(
    transport.start({
      connection: {
        transport: "mock",
        websocket_url: null,
        expires_at: futureIso(15),
      },
      microphone: {},
      signal: new AbortController().signal,
      onEvent: () => {},
    }),
    /Invalid WebSocket transport configuration/,
  );
});

test("mock transport skips capture while live transport preserves audio constraints", async () => {
  assert.equal(voiceTransportRequiresMicrophone("mock"), false);
  assert.equal(voiceTransportRequiresMicrophone("websocket"), true);

  const requests = [];
  const stream = { getTracks: () => [] };
  const mediaDevices = {
    async getUserMedia(constraints) {
      requests.push(constraints);
      return stream;
    },
  };

  assert.equal(await acquireMicrophoneForTransport("mock", mediaDevices), null);
  assert.equal(requests.length, 0);
  assert.equal(await acquireMicrophoneForTransport("websocket", mediaDevices), stream);
  assert.deepEqual(requests, [{
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  }]);
});

test("live websocket transport fails clearly when microphone capture is absent", async () => {
  const transport = new WebSocketVoiceTransport();
  await assert.rejects(
    transport.start({
      connection: websocketSession().connection,
      microphone: null,
      signal: new AbortController().signal,
      onEvent: () => {},
    }),
    /microphone is required/i,
  );
});

test("pagehide makes an active BFCache snapshot terminal", () => {
  let state = voiceSessionReducer(initialVoiceSessionState, { type: "start" });
  state = voiceSessionReducer(state, { type: "microphone-ready" });
  state = voiceSessionReducer(state, {
    type: "session-created",
    sessionId: "session-1",
    connectionExpiresAt: futureIso(15),
    transport: "mock",
  });
  state = voiceSessionReducer(state, {
    type: "transport-event",
    event: { type: "connected" },
  });

  state = voiceSessionReducer(state, { type: "page-hidden" });

  assert.equal(state.phase, "ended");
  assert.equal(state.sessionId, null);
  assert.equal(state.connectionExpiresAt, null);
  assert.equal(state.providerTransport, null);
});

test("mock bootstrap remains valid without a websocket allowlist", () => {
  const session = websocketSession({
    provider: "mock",
    connection: {
      transport: "mock",
      websocket_url: null,
      expires_at: futureIso(15),
    },
  });
  assert.ok(
    parseVoiceSessionResponse(session, {
      now,
      requireWebsocketHostAllowlist: true,
    }),
  );
});

test("BFF-mode websocket validation is fail-closed without an explicit host", () => {
  const session = websocketSession();
  assert.equal(
    parseVoiceSessionResponse(session, {
      now,
      requireWebsocketHostAllowlist: true,
    }),
    null,
  );
  assert.equal(
    parseVoiceSessionResponse(session, {
      now,
      requireWebsocketHostAllowlist: true,
      allowedWebsocketHosts: ["wrong.example.test"],
    }),
    null,
  );
  assert.ok(
    parseVoiceSessionResponse(session, {
      now,
      requireWebsocketHostAllowlist: true,
      allowedWebsocketHosts: ["voice.example.test"],
    }),
  );
});

test("browser-mode validation allows loopback WS but requires WSS for remote hosts", () => {
  assert.ok(parseVoiceSessionResponse(websocketSession(), { now }));
  assert.ok(
    parseVoiceSessionResponse(
      websocketSession({
        connection: {
          transport: "websocket",
          websocket_url: "ws://127.0.0.1:8000/v1/voice/stream?token=ephemeral",
          expires_at: futureIso(15),
        },
      }),
      { now },
    ),
  );
  assert.equal(
    parseVoiceSessionResponse(
      websocketSession({
        connection: {
          transport: "websocket",
          websocket_url: "ws://voice.example.test/connect",
          expires_at: futureIso(15),
        },
      }),
      { now },
    ),
    null,
  );
});

test("voice bootstrap expiration is bounded and connection cannot outlive the session", () => {
  assert.equal(
    parseVoiceSessionResponse(
      websocketSession({
        expires_at: futureIso(70),
        connection: {
          transport: "websocket",
          websocket_url: "wss://voice.example.test/connect",
          expires_at: futureIso(70),
        },
      }),
      { now, allowedWebsocketHosts: ["voice.example.test"] },
    ),
    null,
  );
  assert.equal(
    parseVoiceSessionResponse(
      websocketSession({
        expires_at: futureIso(10),
        connection: {
          transport: "websocket",
          websocket_url: "wss://voice.example.test/connect",
          expires_at: futureIso(11),
        },
      }),
      { now, allowedWebsocketHosts: ["voice.example.test"] },
    ),
    null,
  );
});

test("terminal bootstrap responses never expose connection metadata", () => {
  assert.equal(
    parseVoiceSessionResponse(websocketSession({ status: "completed" }), {
      now,
      allowedWebsocketHosts: ["voice.example.test"],
      requireWebsocketHostAllowlist: true,
    }),
    null,
  );
});

test("cancel response parser keeps only the bounded public contract", () => {
  assert.deepEqual(
    parseCancelVoiceSessionResponse({
      session_id: "session-1",
      status: "cancelled",
      idempotent: false,
      provider_session_id: "must-not-cross-the-bff",
    }),
    {
      session_id: "session-1",
      status: "cancelled",
      idempotent: false,
    },
  );
  assert.equal(
    parseCancelVoiceSessionResponse({
      session_id: "session-1",
      status: "deleting",
      idempotent: false,
    }),
    null,
  );
});

test("cancellation retry policy is bounded and honors numeric Retry-After", () => {
  assert.equal(CANCEL_MAX_ATTEMPTS - 1, 2);
  assert.equal(shouldRetryCancellationResponse(503), true);
  assert.equal(shouldRetryCancellationResponse(200, "cancelling"), true);
  assert.equal(shouldRetryCancellationResponse(400), false);
  assert.equal(isTerminalCancellationStatus("cancelled"), true);
  assert.equal(isTerminalCancellationStatus("completed"), true);

  assert.equal(parseRetryAfterSeconds("3"), 3);
  assert.equal(parseRetryAfterSeconds("not-a-number"), undefined);
  assert.equal(parseRetryAfterSeconds("999999"), 3_600);
  assert.equal(boundedRetryAfterMilliseconds("1", 500, 1_500), 1_000);
  assert.equal(boundedRetryAfterMilliseconds("3", 500, 1_500), 1_500);
  assert.equal(boundedRetryAfterMilliseconds(null, 500, 1_500), 500);
});

test("connection expiry delay is immediate when stale and capped when distant", () => {
  assert.equal(
    connectionExpiryDelayMilliseconds("2026-03-03T10:00:12.000Z", now),
    12_000,
  );
  assert.equal(
    connectionExpiryDelayMilliseconds("2026-03-03T09:59:59.000Z", now),
    0,
  );
  assert.equal(connectionExpiryDelayMilliseconds("invalid", now), 0);
  assert.equal(
    connectionExpiryDelayMilliseconds("2027-03-03T10:00:00.000Z", now),
    MAX_CONNECTION_EXPIRY_DELAY_MS,
  );
});

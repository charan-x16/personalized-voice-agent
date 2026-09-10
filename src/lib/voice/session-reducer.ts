import type { VoicePhase, VoiceTransportEvent } from "./contracts";

export type VoiceTranscriptItem = {
  id: string;
  speaker: "You" | "Svara";
  text: string;
  final: boolean;
};

export type VoiceSessionState = {
  phase: VoicePhase;
  muted: boolean;
  elapsed: number;
  transcript: VoiceTranscriptItem[];
  errorMessage: string | null;
  activePrompt: string | null;
  sessionId: string | null;
  connectionExpiresAt: string | null;
  providerTransport: "mock" | "websocket" | null;
  providerCompleted: boolean;
};

export const initialVoiceSessionState: VoiceSessionState = {
  phase: "ready",
  muted: false,
  elapsed: 0,
  transcript: [],
  errorMessage: null,
  activePrompt: null,
  sessionId: null,
  connectionExpiresAt: null,
  providerTransport: null,
  providerCompleted: false,
};

export type VoiceSessionAction =
  | { type: "start" }
  | { type: "microphone-ready" }
  | {
      type: "session-created";
      sessionId: string;
      connectionExpiresAt: string;
      transport: "mock" | "websocket";
    }
  | { type: "transport-event"; event: VoiceTransportEvent }
  | { type: "prompt-sent"; prompt: string }
  | { type: "set-muted"; muted: boolean }
  | { type: "tick" }
  | { type: "ending" }
  | { type: "ended"; warning?: string }
  | { type: "failed"; message: string }
  | { type: "page-hidden" }
  | { type: "reset" };

const transportEventPhases = new Set<VoicePhase>([
  "connecting",
  "listening",
  "thinking",
  "speaking",
]);

function applyTranscript(
  transcript: VoiceTranscriptItem[],
  event: Extract<VoiceTransportEvent, { type: "transcript" }>,
): VoiceTranscriptItem[] {
  const item: VoiceTranscriptItem = {
    id: event.turnId,
    speaker: event.speaker === "agent" ? "Svara" : "You",
    text: event.text,
    final: event.final,
  };
  const existingIndex = transcript.findIndex((turn) => turn.id === event.turnId);
  if (existingIndex === -1) return [...transcript, item];

  return transcript.map((turn, index) => (index === existingIndex ? item : turn));
}

function applyTransportEvent(
  state: VoiceSessionState,
  event: VoiceTransportEvent,
): VoiceSessionState {
  if (!transportEventPhases.has(state.phase)) return state;

  switch (event.type) {
    case "connected":
      return { ...state, phase: "listening" };
    case "state":
      return {
        ...state,
        phase: event.state,
        activePrompt: event.state === "listening" ? null : state.activePrompt,
      };
    case "transcript":
      return { ...state, transcript: applyTranscript(state.transcript, event) };
    case "completed":
      return { ...state, providerCompleted: true };
    case "closed":
      return event.expected
        ? state
        : {
            ...state,
            phase: "error",
            errorMessage: event.reason || "The voice connection closed unexpectedly.",
          };
    case "error":
      return { ...state, phase: "error", errorMessage: event.message };
  }
}

export function voiceSessionReducer(
  state: VoiceSessionState,
  action: VoiceSessionAction,
): VoiceSessionState {
  switch (action.type) {
    case "start":
      return { ...initialVoiceSessionState, phase: "requesting" };
    case "microphone-ready":
      return state.phase === "requesting" ? { ...state, phase: "connecting" } : state;
    case "session-created":
      return state.phase === "requesting" || state.phase === "connecting"
        ? {
            ...state,
            sessionId: action.sessionId,
            connectionExpiresAt: action.connectionExpiresAt,
            providerTransport: action.transport,
          }
        : state;
    case "transport-event":
      return applyTransportEvent(state, action.event);
    case "prompt-sent":
      return state.phase === "listening"
        ? { ...state, activePrompt: action.prompt }
        : state;
    case "set-muted":
      return transportEventPhases.has(state.phase) ? { ...state, muted: action.muted } : state;
    case "tick":
      return state.sessionId && transportEventPhases.has(state.phase)
        ? { ...state, elapsed: state.elapsed + 1 }
        : state;
    case "ending":
      return transportEventPhases.has(state.phase) || state.phase === "requesting"
        ? { ...state, phase: "ending", muted: false, activePrompt: null }
        : state;
    case "ended":
      return {
        ...state,
        phase: "ended",
        muted: false,
        activePrompt: null,
        sessionId: null,
        connectionExpiresAt: null,
        providerTransport: null,
        errorMessage: action.warning ?? null,
      };
    case "failed":
      return {
        ...state,
        phase: "error",
        muted: false,
        activePrompt: null,
        sessionId: null,
        connectionExpiresAt: null,
        providerTransport: null,
        errorMessage: action.message,
      };
    case "page-hidden":
      return transportEventPhases.has(state.phase) ||
        state.phase === "requesting" ||
        state.phase === "ending"
        ? {
            ...state,
            phase: "ended",
            muted: false,
            activePrompt: null,
            sessionId: null,
            connectionExpiresAt: null,
            providerTransport: null,
            errorMessage: null,
          }
        : state;
    case "reset":
      return initialVoiceSessionState;
  }
}

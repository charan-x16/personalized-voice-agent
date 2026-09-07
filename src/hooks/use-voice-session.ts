"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import type { VoiceSessionResponse } from "@/lib/api-types";
import { parseCancelVoiceSessionResponse, parseVoiceSessionResponse } from "@/lib/api-validation";
import { boundedRetryAfterMilliseconds } from "@/lib/retry-after";
import {
  CANCEL_MAX_ATTEMPTS,
  isTerminalCancellationStatus,
  shouldRetryCancellationResponse,
} from "@/lib/voice/cancellation-policy";
import { connectionExpiryDelayMilliseconds } from "@/lib/voice/connection-expiry";
import type { VoiceStopReason, VoiceTransport, VoiceTransportEvent } from "@/lib/voice/contracts";
import { VoiceTransportError } from "@/lib/voice/contracts";
import {
  initialVoiceSessionState,
  voiceSessionReducer,
  type VoiceSessionState,
} from "@/lib/voice/session-reducer";
import { createVoiceTransport } from "@/lib/voice/transport-factory";

export type VoiceSuggestion = {
  prompt: string;
  response: string;
};

type UseVoiceSessionOptions = {
  firstName: string;
  openingMessage: string;
  preferredLanguage: string;
  suggestions: VoiceSuggestion[];
};

type ActiveSession = {
  id: string;
  transport: VoiceSessionResponse["connection"]["transport"];
  connectionExpiresAt: string;
};

const timedPhases = new Set<VoiceSessionState["phase"]>([
  "connecting",
  "listening",
  "thinking",
  "speaking",
]);

const CANCEL_REQUEST_TIMEOUT_MS = 2_500;
const CANCEL_DEFAULT_RETRY_DELAY_MS = 500;
const CANCEL_MAX_RETRY_DELAY_MS = 1_500;

async function readApiError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof payload.detail === "string"
    ) {
      return payload.detail;
    }
  } catch {
    // The BFF can return an empty response when the request is interrupted.
  }
  return "The voice service is temporarily unavailable.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function startErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "Microphone permission was declined. Allow access from your browser settings to continue.";
    }
    if (error.name === "NotFoundError") {
      return "No microphone was found. Connect one and try again.";
    }
    if (error.name === "NotReadableError") {
      return "Your microphone is being used by another application.";
    }
  }
  if (error instanceof VoiceTransportError || error instanceof Error) return error.message;
  return "The voice session could not be started.";
}

async function requestVoiceSession(
  language: string,
  signal: AbortSignal,
): Promise<VoiceSessionResponse> {
  const response = await fetch("/api/voice/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language }),
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(await readApiError(response));

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The voice service returned an invalid session.");
  }
  const session = parseVoiceSessionResponse(payload);
  if (!session) throw new Error("The voice service returned an invalid session.");
  return session;
}

function cancellationRetryDelay(response: Response | null): number {
  return boundedRetryAfterMilliseconds(
    response?.headers.get("retry-after") ?? null,
    CANCEL_DEFAULT_RETRY_DELAY_MS,
    CANCEL_MAX_RETRY_DELAY_MS,
  );
}

function waitForRetry(delay: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delay));
}

async function cancelVoiceSession(sessionId: string, keepalive: boolean): Promise<boolean> {
  const attempts = keepalive ? 1 : CANCEL_MAX_ATTEMPTS;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    let response: Response | null = null;
    try {
      response = await fetch(
        `/api/voice/sessions/${encodeURIComponent(sessionId)}/cancel`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
          cache: "no-store",
          keepalive,
          ...(keepalive ? {} : { signal: AbortSignal.timeout(CANCEL_REQUEST_TIMEOUT_MS) }),
        },
      );

      if (response.ok) {
        const cancellation = parseCancelVoiceSessionResponse(await response.json());
        if (!cancellation || cancellation.session_id !== sessionId) return false;
        if (isTerminalCancellationStatus(cancellation.status)) return true;
        if (!shouldRetryCancellationResponse(response.status, cancellation.status)) return false;
      } else if (!shouldRetryCancellationResponse(response.status)) {
        return false;
      }
    } catch {
      // A network failure is ambiguous, so normal cleanup gets a bounded retry.
    }

    if (attempt + 1 < attempts) {
      await waitForRetry(cancellationRetryDelay(response));
    }
  }

  return false;
}

async function completeMockSession(
  sessionId: string,
  state: VoiceSessionState,
): Promise<void> {
  const latestAgentMessage = [...state.transcript]
    .reverse()
    .find((item) => item.speaker === "Svara" && item.final);
  const response = await fetch(
    `/api/voice/sessions/${encodeURIComponent(sessionId)}/mock-complete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resolution: "resolved",
        summary: latestAgentMessage?.text ?? "Mock voice session completed.",
        transcript: state.transcript
          .filter((item) => item.final)
          .map((item) => ({
            speaker: item.speaker === "Svara" ? "agent" : "customer",
            text: item.text,
          })),
        duration_seconds: state.elapsed,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    },
  );
  if (!response.ok) throw new Error(await readApiError(response));
}

export function useVoiceSession({
  firstName,
  openingMessage,
  preferredLanguage,
  suggestions,
}: UseVoiceSessionOptions) {
  const [state, dispatch] = useReducer(voiceSessionReducer, initialVoiceSessionState);
  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const activeStartRef = useRef<number | null>(null);
  const endingRef = useRef(false);
  const microphoneRef = useRef<MediaStream | null>(null);
  const transportRef = useRef<VoiceTransport | null>(null);
  const connectionExpiryTimerRef = useRef<number | null>(null);
  const lifecycleControllerRef = useRef<AbortController | null>(null);
  const activeSessionRef = useRef<ActiveSession | null>(null);
  const providerCompletedRef = useRef(false);

  const responseByPrompt = useMemo(
    () => new Map(suggestions.map((suggestion) => [suggestion.prompt, suggestion.response])),
    [suggestions],
  );

  useEffect(() => {
    if (!state.sessionId || !timedPhases.has(state.phase)) return;
    const timer = window.setInterval(() => dispatch({ type: "tick" }), 1_000);
    return () => window.clearInterval(timer);
  }, [state.phase, state.sessionId]);

  const releaseMicrophone = useCallback(() => {
    microphoneRef.current?.getTracks().forEach((track) => track.stop());
    microphoneRef.current = null;
  }, []);

  const clearConnectionExpiryTimer = useCallback(() => {
    if (connectionExpiryTimerRef.current !== null) {
      window.clearTimeout(connectionExpiryTimerRef.current);
      connectionExpiryTimerRef.current = null;
    }
  }, []);

  const stopLocalResources = useCallback(
    async (reason: VoiceStopReason) => {
      const controller = lifecycleControllerRef.current;
      const transport = transportRef.current;
      lifecycleControllerRef.current = null;
      transportRef.current = null;
      clearConnectionExpiryTimer();
      controller?.abort();
      releaseMicrophone();
      if (transport) {
        try {
          await transport.stop(reason);
        } catch {
          // Local cleanup must remain idempotent even if a future adapter fails to close.
        }
      }
    },
    [clearConnectionExpiryTimer, releaseMicrophone],
  );

  const cancelActiveSession = useCallback(async (keepalive: boolean) => {
    const activeSession = activeSessionRef.current;
    if (!activeSession) return true;
    if (providerCompletedRef.current) {
      activeSessionRef.current = null;
      return true;
    }

    const cancelled = await cancelVoiceSession(activeSession.id, keepalive);
    if (cancelled && activeSessionRef.current?.id === activeSession.id) {
      activeSessionRef.current = null;
    }
    return cancelled;
  }, []);

  const failActiveRun = useCallback(
    async (run: number, message: string) => {
      if (run !== generationRef.current) return;
      generationRef.current += 1;
      const cleanupGeneration = generationRef.current;
      activeStartRef.current = null;
      await stopLocalResources("error");
      if (mountedRef.current) dispatch({ type: "failed", message });
      const released = await cancelActiveSession(false);
      if (!released && mountedRef.current && generationRef.current === cleanupGeneration) {
        dispatch({
          type: "failed",
          message: `${message} The unfinished session could not be released; cleanup will retry before another call.`,
        });
      }
    },
    [cancelActiveSession, stopLocalResources],
  );

  const completeProviderRun = useCallback(
    async (run: number) => {
      if (!mountedRef.current || run !== generationRef.current) return;

      providerCompletedRef.current = true;
      activeSessionRef.current = null;
      generationRef.current += 1;
      activeStartRef.current = null;
      endingRef.current = true;
      dispatch({ type: "ending" });

      try {
        await stopLocalResources("provider");
        if (mountedRef.current) dispatch({ type: "ended" });
      } finally {
        endingRef.current = false;
      }
    },
    [stopLocalResources],
  );

  const startSession = useCallback(async () => {
    if (activeStartRef.current !== null || endingRef.current) return;

    const run = generationRef.current + 1;
    generationRef.current = run;
    activeStartRef.current = run;
    dispatch({ type: "start" });

    await stopLocalResources("reset");
    const priorSessionReleased = await cancelActiveSession(false);
    if (!priorSessionReleased) {
      activeStartRef.current = null;
      if (mountedRef.current && run === generationRef.current) {
        dispatch({
          type: "failed",
          message: "The previous voice session could not be released. Please try again.",
        });
      }
      return;
    }
    if (!mountedRef.current || run !== generationRef.current) return;
    providerCompletedRef.current = false;

    const controller = new AbortController();
    lifecycleControllerRef.current = controller;

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone access is not supported in this browser.");
      }

      const microphone = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (!mountedRef.current || run !== generationRef.current) {
        microphone.getTracks().forEach((track) => track.stop());
        return;
      }

      microphoneRef.current = microphone;
      dispatch({ type: "microphone-ready" });
      const session = await requestVoiceSession(preferredLanguage, controller.signal);
      if (!mountedRef.current || run !== generationRef.current) {
        void cancelVoiceSession(session.session_id, true);
        return;
      }

      activeSessionRef.current = {
        id: session.session_id,
        transport: session.connection.transport,
        connectionExpiresAt: session.connection.expires_at,
      };
      dispatch({
        type: "session-created",
        sessionId: session.session_id,
        connectionExpiresAt: session.connection.expires_at,
        transport: session.connection.transport,
      });

      connectionExpiryTimerRef.current = window.setTimeout(() => {
        if (!mountedRef.current || run !== generationRef.current) return;
        void failActiveRun(
          run,
          "The secure voice connection expired. Start a new conversation to continue.",
        );
      }, connectionExpiryDelayMilliseconds(session.connection.expires_at));

      const transport = createVoiceTransport({
        session,
        mockGreeting: openingMessage || `Hello ${firstName}. How can I help today?`,
        responseForPrompt: (prompt) => responseByPrompt.get(prompt),
      });
      transportRef.current = transport;

      const onEvent = (event: VoiceTransportEvent) => {
        if (!mountedRef.current || run !== generationRef.current) return;
        if (event.type === "error" || event.type === "closed") {
          const message =
            event.type === "error"
              ? event.message
              : event.reason ||
                (event.expected
                  ? "The voice connection ended before the provider confirmed completion."
                  : "The voice connection closed unexpectedly.");
          void failActiveRun(run, message);
          return;
        }
        if (event.type === "completed") {
          dispatch({ type: "transport-event", event });
          void completeProviderRun(run);
          return;
        }
        dispatch({ type: "transport-event", event });
      };

      await transport.start({
        connection: session.connection,
        microphone,
        signal: controller.signal,
        onEvent,
      });
    } catch (error) {
      if (run !== generationRef.current || isAbortError(error)) return;
      await failActiveRun(run, startErrorMessage(error));
    } finally {
      if (activeStartRef.current === run) activeStartRef.current = null;
    }
  }, [
    cancelActiveSession,
    completeProviderRun,
    failActiveRun,
    firstName,
    openingMessage,
    preferredLanguage,
    responseByPrompt,
    stopLocalResources,
  ]);

  const endSession = useCallback(async () => {
    if (endingRef.current) return;
    endingRef.current = true;
    const snapshot = state;
    generationRef.current += 1;
    activeStartRef.current = null;
    dispatch({ type: "ending" });

    try {
      await stopLocalResources("user");
      const activeSession = activeSessionRef.current;
      if (!activeSession) {
        if (mountedRef.current) dispatch({ type: "ended" });
        return;
      }

      const canCompleteMock =
        activeSession.transport === "mock" &&
        ["listening", "thinking", "speaking"].includes(snapshot.phase);
      if (canCompleteMock) {
        try {
          await completeMockSession(activeSession.id, snapshot);
          providerCompletedRef.current = true;
          activeSessionRef.current = null;
          if (mountedRef.current) dispatch({ type: "ended" });
        } catch (error) {
          const released = await cancelActiveSession(false);
          const detail = error instanceof Error ? error.message : "The outcome could not be saved.";
          if (mountedRef.current) {
            dispatch({
              type: "ended",
              warning: released
                ? `The call ended safely, but it could not be saved: ${detail}`
                : `The call ended, but it could not be saved or released: ${detail}. Cleanup will retry before another call.`,
            });
          }
        }
        return;
      }

      if (activeSession.transport === "mock") {
        const released = await cancelActiveSession(false);
        if (mountedRef.current) {
          dispatch({
            type: "ended",
            warning: released
              ? undefined
              : "The unfinished session could not be released. Cleanup will retry before another call.",
          });
        }
        return;
      }

      const released = await cancelActiveSession(false);
      if (mountedRef.current) {
        dispatch({
          type: "ended",
          warning: released
            ? undefined
            : "The voice connection ended, but the session could not be released. Cleanup will retry before another call.",
        });
      }
    } finally {
      endingRef.current = false;
    }
  }, [cancelActiveSession, state, stopLocalResources]);

  const resetSession = useCallback(() => {
    generationRef.current += 1;
    activeStartRef.current = null;
    void stopLocalResources("reset");
    void cancelActiveSession(false);
    providerCompletedRef.current = false;
    dispatch({ type: "reset" });
  }, [cancelActiveSession, stopLocalResources]);

  const toggleMute = useCallback(() => {
    const nextMuted = !state.muted;
    microphoneRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = !nextMuted;
    });
    transportRef.current?.setInputEnabled(!nextMuted);
    dispatch({ type: "set-muted", muted: nextMuted });
  }, [state.muted]);

  const sendPrompt = useCallback((prompt: string) => {
    const transport = transportRef.current;
    if (!transport?.supportsTextPrompts) return;
    dispatch({ type: "prompt-sent", prompt });
    if (!transport.sendText(prompt)) {
      dispatch({ type: "transport-event", event: { type: "state", state: "listening" } });
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    const handlePageHide = () => {
      generationRef.current += 1;
      activeStartRef.current = null;
      void stopLocalResources("pagehide");
      const cancellation = cancelActiveSession(true);
      providerCompletedRef.current = false;
      dispatch({ type: "page-hidden" });
      void cancellation;
    };
    const handlePageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;

      generationRef.current += 1;
      const restoreGeneration = generationRef.current;
      activeStartRef.current = null;
      void stopLocalResources("pagehide");
      const cancellation = cancelActiveSession(false);
      providerCompletedRef.current = false;
      dispatch({ type: "page-hidden" });
      void cancellation.then((released) => {
        if (!released && mountedRef.current && generationRef.current === restoreGeneration) {
          dispatch({
            type: "ended",
            warning:
              "The restored session could not be released. Cleanup will retry before another call.",
          });
        }
      });
    };
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);

    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      activeStartRef.current = null;
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
      void stopLocalResources("unmount");
      const cancellation = cancelActiveSession(true);
      providerCompletedRef.current = false;
      void cancellation;
    };
  }, [cancelActiveSession, stopLocalResources]);

  return {
    state,
    isActive: timedPhases.has(state.phase) || state.phase === "requesting",
    supportsTextPrompts: state.providerTransport === "mock",
    startSession,
    endSession,
    resetSession,
    toggleMute,
    sendPrompt,
  };
}

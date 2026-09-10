import type {
  VoiceStopReason,
  VoiceTransport,
  VoiceTransportEvent,
  VoiceTransportStartOptions,
} from "./contracts.ts";
import { VoiceTransportError } from "./contracts.ts";

const CONNECT_TIMEOUT_MS = 30_000;
const OUTPUT_SAMPLE_RATE = 16_000;

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export class WebSocketVoiceTransport implements VoiceTransport {
  readonly kind = "websocket" as const;
  readonly supportsTextPrompts = false;

  private websocket: WebSocket | null = null;
  private audioContext: AudioContext | null = null;
  private microphoneSource: MediaStreamAudioSourceNode | null = null;
  private captureNode: AudioWorkletNode | null = null;
  private silentGain: GainNode | null = null;
  private readonly playbackSources = new Set<AudioBufferSourceNode>();
  private nextPlaybackTime = 0;
  private onEvent: ((event: VoiceTransportEvent) => void) | null = null;
  private signal: AbortSignal | null = null;
  private abortHandler: (() => void) | null = null;
  private started = false;
  private providerReady = false;
  private expectedClose = false;
  private completed = false;
  private inputEnabled = true;
  private pendingListeningState = false;

  private emit(event: VoiceTransportEvent) {
    if (this.started) this.onEvent?.(event);
  }

  private stopPlayback() {
    for (const source of this.playbackSources) {
      try {
        source.stop();
      } catch {
        // A source that has already ended is safe to discard.
      }
    }
    this.playbackSources.clear();
    this.nextPlaybackTime = this.audioContext?.currentTime ?? 0;
    this.pendingListeningState = false;
  }

  private playPcm16(buffer: ArrayBuffer) {
    const context = this.audioContext;
    if (!context || buffer.byteLength < 2 || buffer.byteLength % 2 !== 0) return;

    const view = new DataView(buffer);
    const samples = new Float32Array(buffer.byteLength / 2);
    for (let index = 0; index < samples.length; index += 1) {
      samples[index] = view.getInt16(index * 2, true) / 32_768;
    }

    const audioBuffer = context.createBuffer(1, samples.length, OUTPUT_SAMPLE_RATE);
    audioBuffer.copyToChannel(samples, 0);
    const source = context.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(context.destination);
    source.onended = () => {
      this.playbackSources.delete(source);
      if (this.playbackSources.size === 0 && this.pendingListeningState) {
        this.pendingListeningState = false;
        this.emit({ type: "state", state: "listening" });
      }
    };
    this.playbackSources.add(source);

    const startAt = Math.max(context.currentTime + 0.015, this.nextPlaybackTime);
    source.start(startAt);
    this.nextPlaybackTime = startAt + audioBuffer.duration;
  }

  private handleControlMessage(raw: string) {
    let payload: Record<string, unknown> | null = null;
    try {
      payload = asRecord(JSON.parse(raw));
    } catch {
      // Invalid provider messages fail the transport closed below.
    }
    if (!payload || typeof payload.type !== "string") {
      this.emit({
        type: "error",
        code: "invalid_provider_message",
        message: "The voice service returned an invalid message.",
      });
      this.expectedClose = true;
      this.websocket?.close(1008, "Invalid provider message");
      return;
    }

    if (payload.type === "connected") {
      if (!this.providerReady) {
        this.providerReady = true;
        this.emit({ type: "connected" });
      }
      return;
    }
    if (
      payload.type === "state" &&
      (payload.state === "listening" ||
        payload.state === "thinking" ||
        payload.state === "speaking")
    ) {
      if (payload.state === "listening" && this.playbackSources.size > 0) {
        this.pendingListeningState = true;
        return;
      }
      if (payload.state === "speaking") this.pendingListeningState = false;
      this.emit({ type: "state", state: payload.state });
      return;
    }
    if (payload.type === "interrupt") {
      this.stopPlayback();
      return;
    }
    if (
      payload.type === "transcript" &&
      typeof payload.turn_id === "string" &&
      (payload.speaker === "customer" || payload.speaker === "agent") &&
      typeof payload.text === "string" &&
      typeof payload.final === "boolean"
    ) {
      this.emit({
        type: "transcript",
        turnId: payload.turn_id,
        speaker: payload.speaker,
        text: payload.text,
        final: payload.final,
      });
      return;
    }
    if (payload.type === "completed") {
      this.completed = true;
      this.expectedClose = true;
      this.stopPlayback();
      this.emit({ type: "completed" });
      return;
    }
    if (
      payload.type === "error" &&
      typeof payload.code === "string" &&
      typeof payload.message === "string"
    ) {
      this.expectedClose = true;
      this.emit({ type: "error", code: payload.code, message: payload.message });
      return;
    }

    this.emit({
      type: "error",
      code: "unsupported_provider_message",
      message: "The voice service returned an unsupported message.",
    });
    this.expectedClose = true;
    this.websocket?.close(1008, "Unsupported provider message");
  }

  private async initializeAudio(microphone: MediaStream) {
    const context = new AudioContext({ latencyHint: "interactive" });
    this.audioContext = context;
    await context.audioWorklet.addModule("/pcm-capture-worklet.js");
    if (context.state === "suspended") await context.resume();

    const source = context.createMediaStreamSource(microphone);
    const capture = new AudioWorkletNode(context, "pcm-capture-processor", {
      processorOptions: { outputSampleRate: OUTPUT_SAMPLE_RATE, frameSize: 320 },
    });
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    capture.port.onmessage = (event: MessageEvent<unknown>) => {
      if (
        this.started &&
        this.providerReady &&
        this.inputEnabled &&
        event.data instanceof ArrayBuffer &&
        this.websocket?.readyState === WebSocket.OPEN
      ) {
        this.websocket.send(event.data);
      }
    };
    source.connect(capture);
    capture.connect(silentGain);
    silentGain.connect(context.destination);
    capture.port.postMessage({ type: "set-enabled", enabled: this.inputEnabled });

    this.microphoneSource = source;
    this.captureNode = capture;
    this.silentGain = silentGain;
    this.nextPlaybackTime = context.currentTime;
  }

  private async cleanupAudio() {
    this.stopPlayback();
    this.captureNode?.port.postMessage({ type: "set-enabled", enabled: false });
    this.captureNode?.disconnect();
    this.microphoneSource?.disconnect();
    this.silentGain?.disconnect();
    this.captureNode = null;
    this.microphoneSource = null;
    this.silentGain = null;
    const context = this.audioContext;
    this.audioContext = null;
    if (context && context.state !== "closed") await context.close();
  }

  async start(options: VoiceTransportStartOptions): Promise<void> {
    if (options.connection.transport !== "websocket") {
      throw new VoiceTransportError(
        "transport_mismatch",
        "Invalid WebSocket transport configuration.",
      );
    }
    if (!options.microphone) {
      throw new VoiceTransportError(
        "microphone_required",
        "A microphone is required for a live voice session.",
      );
    }
    if (this.started) {
      throw new VoiceTransportError("already_started", "The voice transport is already active.");
    }
    if (options.signal.aborted) throw abortError();

    this.started = true;
    this.onEvent = options.onEvent;
    this.signal = options.signal;
    this.expectedClose = false;
    this.completed = false;
    this.providerReady = false;
    this.pendingListeningState = false;

    try {
      await this.initializeAudio(options.microphone);
      if (options.signal.aborted) throw abortError();

      const connectionUrl = new URL(options.connection.websocket_url);
      const relayToken = connectionUrl.searchParams.get("token");
      if (!relayToken || Array.from(connectionUrl.searchParams.keys()).some((key) => key !== "token")) {
        throw new VoiceTransportError(
          "invalid_relay_credential",
          "The secure voice connection is missing its relay credential.",
        );
      }
      connectionUrl.search = "";
      const websocket = new WebSocket(connectionUrl, [
        "svara-relay",
        `svara-token.${relayToken.replace(/=+$/u, "")}`,
      ]);
      websocket.binaryType = "arraybuffer";
      this.websocket = websocket;

      await new Promise<void>((resolve, reject) => {
        let settled = false;
        const settleResolve = () => {
          if (settled) return;
          settled = true;
          globalThis.clearTimeout(timeout);
          resolve();
        };
        const settleReject = (error: Error) => {
          if (settled) return;
          settled = true;
          globalThis.clearTimeout(timeout);
          reject(error);
        };
        const timeout = globalThis.setTimeout(() => {
          this.expectedClose = true;
          websocket.close(1000, "Connection timeout");
          settleReject(
            new VoiceTransportError(
              "connection_timeout",
              "The live voice service did not connect in time.",
            ),
          );
        }, CONNECT_TIMEOUT_MS);

        this.abortHandler = () => {
          this.expectedClose = true;
          websocket.close(1000, "Aborted");
          settleReject(abortError());
        };
        options.signal.addEventListener("abort", this.abortHandler, { once: true });

        websocket.onmessage = (event) => {
          if (typeof event.data === "string") {
            const wasReady = this.providerReady;
            this.handleControlMessage(event.data);
            if (!wasReady && this.providerReady) settleResolve();
            return;
          }
          if (event.data instanceof ArrayBuffer) this.playPcm16(event.data);
        };
        websocket.onerror = () => {
          const error = new VoiceTransportError(
            "websocket_error",
            "The secure voice connection could not be established.",
          );
          if (!this.providerReady) settleReject(error);
          else this.emit({ type: "error", code: error.code, message: error.message });
        };
        websocket.onclose = (event) => {
          const wasReady = this.providerReady;
          this.providerReady = false;
          void this.cleanupAudio();
          if (!wasReady) {
            settleReject(
              new VoiceTransportError(
                "connection_closed",
                "The secure voice connection closed before the agent was ready.",
              ),
            );
          } else if (!this.completed) {
            this.emit({
              type: "closed",
              expected: this.expectedClose,
              ...(event.reason ? { reason: event.reason } : {}),
            });
          }
        };
      });
    } catch (error) {
      await this.stop("error");
      throw error;
    }
  }

  setInputEnabled(enabled: boolean): void {
    this.inputEnabled = enabled;
    this.captureNode?.port.postMessage({ type: "set-enabled", enabled });
  }

  sendText(): boolean {
    return false;
  }

  async stop(reason: VoiceStopReason): Promise<void> {
    if (!this.started && !this.websocket && !this.audioContext) return;
    this.expectedClose = true;
    this.providerReady = false;
    this.inputEnabled = false;
    this.pendingListeningState = false;
    this.captureNode?.port.postMessage({ type: "set-enabled", enabled: false });

    const websocket = this.websocket;
    this.websocket = null;
    if (websocket?.readyState === WebSocket.OPEN) {
      try {
        websocket.send(JSON.stringify({ type: "end" }));
      } catch {
        // The close below is the final local cleanup path.
      }
    }
    if (websocket && websocket.readyState < WebSocket.CLOSING) {
      websocket.close(1000, reason);
    }

    if (this.signal && this.abortHandler) {
      this.signal.removeEventListener("abort", this.abortHandler);
    }
    this.signal = null;
    this.abortHandler = null;
    this.onEvent = null;
    this.started = false;
    await this.cleanupAudio();
  }
}

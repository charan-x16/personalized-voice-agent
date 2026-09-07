import type {
  VoiceTransport,
  VoiceTransportEvent,
  VoiceTransportStartOptions,
} from "./contracts";
import { VoiceTransportError } from "./contracts";

type MockVoiceTransportOptions = {
  greeting: string;
  responseForPrompt: (prompt: string) => string | undefined;
};

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

export class MockVoiceTransport implements VoiceTransport {
  readonly kind = "mock" as const;
  readonly supportsTextPrompts = true;

  private readonly timers = new Set<ReturnType<typeof setTimeout>>();
  private onEvent: ((event: VoiceTransportEvent) => void) | null = null;
  private abortHandler: (() => void) | null = null;
  private signal: AbortSignal | null = null;
  private started = false;
  private acceptingInput = false;
  private inputEnabled = true;
  private turn = 0;

  constructor(private readonly options: MockVoiceTransportOptions) {}

  private emit(event: VoiceTransportEvent) {
    if (this.started) this.onEvent?.(event);
  }

  private schedule(callback: () => void, delay: number) {
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      if (this.started) callback();
    }, delay);
    this.timers.add(timer);
  }

  async start(options: VoiceTransportStartOptions): Promise<void> {
    if (options.connection.transport !== "mock") {
      throw new VoiceTransportError("transport_mismatch", "Invalid mock transport configuration.");
    }
    if (options.signal.aborted) throw abortError();

    this.started = true;
    this.onEvent = options.onEvent;
    this.signal = options.signal;
    this.abortHandler = () => {
      void this.stop();
    };
    options.signal.addEventListener("abort", this.abortHandler, { once: true });

    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        clearTimeout(timer);
        this.timers.delete(timer);
        reject(abortError());
      };
      const timer = setTimeout(() => {
        this.timers.delete(timer);
        options.signal.removeEventListener("abort", onAbort);
        resolve();
      }, 900);
      this.timers.add(timer);
      options.signal.addEventListener("abort", onAbort, { once: true });
    });

    if (!this.started || options.signal.aborted) throw abortError();
    this.emit({ type: "connected" });
    this.turn += 1;
    this.emit({
      type: "transcript",
      turnId: `mock-agent-${this.turn}`,
      speaker: "agent",
      text: this.options.greeting,
      final: true,
    });
    this.emit({ type: "state", state: "speaking" });
    this.schedule(() => {
      this.acceptingInput = true;
      this.emit({ type: "state", state: "listening" });
    }, 1_800);
  }

  setInputEnabled(enabled: boolean): void {
    this.inputEnabled = enabled;
  }

  sendText(text: string): boolean {
    if (!this.started || !this.acceptingInput || !this.inputEnabled) return false;
    const response = this.options.responseForPrompt(text);
    if (!response) return false;

    this.acceptingInput = false;
    this.turn += 1;
    this.emit({
      type: "transcript",
      turnId: `mock-customer-${this.turn}`,
      speaker: "customer",
      text,
      final: true,
    });
    this.emit({ type: "state", state: "thinking" });

    this.schedule(() => {
      this.turn += 1;
      this.emit({
        type: "transcript",
        turnId: `mock-agent-${this.turn}`,
        speaker: "agent",
        text: response,
        final: true,
      });
      this.emit({ type: "state", state: "speaking" });
      this.schedule(() => {
        this.acceptingInput = true;
        this.emit({ type: "state", state: "listening" });
      }, 3_100);
    }, 1_250);
    return true;
  }

  async stop(): Promise<void> {
    if (!this.started) return;
    this.started = false;
    this.acceptingInput = false;
    this.timers.forEach((timer) => clearTimeout(timer));
    this.timers.clear();
    if (this.signal && this.abortHandler) {
      this.signal.removeEventListener("abort", this.abortHandler);
    }
    this.signal = null;
    this.abortHandler = null;
    this.onEvent = null;
  }
}

"use client";

import {
  Check,
  ChevronDown,
  Clock3,
  LockKeyhole,
  Mic,
  MicOff,
  PhoneOff,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useVoiceSession, type VoiceSuggestion } from "@/hooks/use-voice-session";
import type { VoicePhase } from "@/lib/voice/contracts";
import { isNearTranscriptBottom } from "@/lib/voice/transcript-scroll";
import styles from "./voice-session.module.css";

export type VoiceProfile = {
  firstName: string;
  fullName: string;
  initials: string;
  workspaceName: string;
  planName: string;
  preferredLanguage: string;
  agentName: string;
  openingMessage: string;
  isDemo: boolean;
};

const stateContent: Record<VoicePhase, { eyebrow: string; title: string; detail: string }> = {
  ready: {
    eyebrow: "Private voice session",
    title: "Your assistant is ready.",
    detail: "Start when you’re comfortable. Your account context will load securely.",
  },
  requesting: {
    eyebrow: "Microphone access",
    title: "One small permission.",
    detail: "Allow microphone access in your browser to begin the conversation.",
  },
  connecting: {
    eyebrow: "Establishing session",
    title: "Connecting securely…",
    detail: "Preparing your assistant and loading the right customer context.",
  },
  listening: {
    eyebrow: "Listening",
    title: "Go ahead.",
    detail: "Speak naturally, or choose one of the prompts below to try the experience.",
  },
  thinking: {
    eyebrow: "Checking your account",
    title: "One moment…",
    detail: "Your assistant is securely retrieving the information you asked for.",
  },
  speaking: {
    eyebrow: "Your assistant is speaking",
    title: "Here’s what I found.",
    detail: "You can interrupt at any time and continue in your own words.",
  },
  ending: {
    eyebrow: "Closing securely",
    title: "Ending the conversation...",
    detail: "Disconnecting your microphone and closing the secure session.",
  },
  ended: {
    eyebrow: "Session complete",
    title: "Conversation ended.",
    detail: "Your microphone is disconnected. Saved outcomes will appear in the archive.",
  },
  error: {
    eyebrow: "Session unavailable",
    title: "We couldn’t connect.",
    detail: "Check the message below, then try starting the conversation again.",
  },
};

function formatElapsed(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function AcousticRibbon({ state }: { state: VoicePhase }) {
  return (
    <div className={styles.visual} data-state={state}>
      <span className={styles.orbit} />
      <span className={styles.orbitInner} />
      <svg
        className={styles.ribbon}
        viewBox="0 0 420 240"
        role="img"
        aria-label={`Voice visualization: ${stateContent[state].eyebrow}`}
      >
        <defs>
          <linearGradient id="ribbon-ember" x1="30" y1="120" x2="390" y2="120" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#df5f3f" stopOpacity="0" />
            <stop offset="0.27" stopColor="#df5f3f" stopOpacity="0.52" />
            <stop offset="0.5" stopColor="#f38463" />
            <stop offset="0.73" stopColor="#df5f3f" stopOpacity="0.52" />
            <stop offset="1" stopColor="#df5f3f" stopOpacity="0" />
          </linearGradient>
          <filter id="ribbon-glow" x="-20%" y="-60%" width="140%" height="220%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <path
          className={`${styles.wave} ${styles.waveGhost}`}
          d="M24 120 C66 120 71 97 111 97 C153 97 151 148 194 148 C239 148 239 78 283 78 C329 78 330 120 396 120"
        />
        <path
          className={`${styles.wave} ${styles.waveSoft}`}
          d="M24 120 C70 120 78 108 114 108 C152 108 160 136 197 136 C236 136 245 92 282 92 C325 92 334 120 396 120"
        />
        <path
          className={`${styles.wave} ${styles.waveCore}`}
          d="M24 120 C72 120 79 116 115 116 C150 116 166 128 199 128 C234 128 250 106 282 106 C324 106 343 120 396 120"
        />
      </svg>
      <span className={styles.pulseDot} />
    </div>
  );
}

export function VoiceSession({ profile }: { profile: VoiceProfile }) {
  const suggestions = useMemo<VoiceSuggestion[]>(
    () => [
      {
        prompt: "Which plan am I on?",
        response: `You're on the ${profile.planName} plan. I can use that context while helping with this conversation.`,
      },
      {
        prompt: "Which language do I prefer?",
        response: `Your saved preference is ${profile.preferredLanguage}. A live provider can use it when the session starts.`,
      },
      {
        prompt: "How is my data protected?",
        response: `This session is scoped to your verified ${profile.workspaceName} profile. The browser never receives the private database lookup key.`,
      },
    ],
    [profile.planName, profile.preferredLanguage, profile.workspaceName],
  );
  const {
    state,
    isActive,
    supportsTextPrompts,
    startSession,
    endSession,
    resetSession,
    toggleMute,
    sendPrompt,
  } = useVoiceSession({
    firstName: profile.firstName,
    openingMessage: profile.openingMessage,
    preferredLanguage: profile.preferredLanguage,
    suggestions,
  });
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const followTranscriptRef = useRef(true);
  const [readingHistory, setReadingHistory] = useState(false);
  const {
    phase: voiceState,
    muted,
    elapsed,
    transcript,
    errorMessage,
    activePrompt,
    providerTransport,
  } = state;

  useEffect(() => {
    if (transcriptRef.current && followTranscriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [transcript, voiceState]);

  const content = stateContent[voiceState];
  const isDemo = providerTransport === "mock" || (!providerTransport && profile.isDemo);
  const statusEyebrow = isDemo && ["ready", "listening", "speaking"].includes(voiceState)
    ? voiceState === "listening" ? "Choose a prompt" : voiceState === "speaking" ? "Demo response" : "Text-only demo"
    : content.eyebrow;
  const statusDetail = isDemo
    ? voiceState === "ready"
      ? "This is a text-based demo. Starting requests microphone permission, but audio is not sent or transcribed. Use a suggested prompt to explore."
      : voiceState === "listening"
        ? "Choose a suggested prompt below. This demo does not listen to or transcribe your voice."
        : voiceState === "speaking"
          ? "Your demo response is shown in the transcript. No voice audio is playing."
          : content.detail
    : content.detail;
  const statusTitle =
    voiceState === "listening" ? `Go ahead, ${profile.firstName}.` : content.title;
  const announcedStatus = muted
    ? "Microphone muted"
    : `${statusEyebrow}. ${statusTitle}`;

  const lastAgentMessage = useMemo(
    () => [...transcript].reverse().find((item) => item.speaker === "Svara"),
    [transcript],
  );
  function beginSession() {
    followTranscriptRef.current = true;
    setReadingHistory(false);
    void startSession();
  }
  return (
    <div className={styles.page} data-active={isActive}>
      <div className={styles.topbar}>
        <div>
          <p className="eyebrow">Voice room</p>
          <h1>Talk to {profile.agentName}</h1>
        </div>
        <div className={styles.sessionMeta} aria-label="Session details">
          <span className={styles.secureBadge}>
            <LockKeyhole size={13} strokeWidth={1.9} />
            {isDemo ? "Demo · text only" : providerTransport ? "Private session" : "Ready to connect"}
          </span>
          <span className={styles.timer}>
            <Clock3 size={14} strokeWidth={1.8} />
            <time>{formatElapsed(elapsed)}</time>
          </span>
        </div>
      </div>

      <div className={styles.workspace}>
        <section className={styles.callPanel} aria-label="Voice conversation">
          <div className={styles.statusCopy}>
            <span className={styles.statusLine}>
              <i aria-hidden="true" data-state={voiceState} />
              {muted ? "Microphone muted" : statusEyebrow}
            </span>
            <h2>{muted && voiceState === "listening" ? "I’ll wait here." : statusTitle}</h2>
            <p>{muted ? "Unmute whenever you’re ready to continue." : statusDetail}</p>
          </div>

          <AcousticRibbon state={muted ? "ready" : voiceState} />

          <div className={styles.primaryActions} data-active={isActive}>
            {voiceState === "ready" && (
              <button className={styles.startButton} type="button" onClick={beginSession}>
                <Mic size={18} strokeWidth={2} />
                Start conversation
              </button>
            )}

            {isActive && (
              <>
                <button
                  className={`${styles.roundControl} ${muted ? styles.controlActive : ""}`}
                  type="button"
                  onClick={toggleMute}
                  disabled={voiceState === "requesting" || voiceState === "connecting"}
                  aria-label={muted ? "Unmute microphone" : "Mute microphone"}
                  aria-pressed={muted}
                >
                  {muted ? <MicOff size={20} /> : <Mic size={20} />}
                  <span>{muted ? "Unmute" : "Mute"}</span>
                </button>
                <button className={`${styles.roundControl} ${styles.endControl}`} type="button" onClick={endSession}>
                  <PhoneOff size={20} />
                  <span>End</span>
                </button>
              </>
            )}

            {(voiceState === "ended" || voiceState === "error") && (
              <button className={styles.startButton} type="button" onClick={beginSession}>
                <RotateCcw size={17} strokeWidth={2} />
                {voiceState === "error" ? "Try again" : "Start a new session"}
              </button>
            )}
          </div>

          {errorMessage && (voiceState === "error" || voiceState === "ended") && (
            <p className={styles.errorNote}>{errorMessage}</p>
          )}

          <div className={styles.promptArea} aria-label="Conversation suggestions">
            <span>Try asking</span>
            <div className={styles.promptList}>
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion.prompt}
                  className={styles.prompt}
                  type="button"
                  disabled={voiceState !== "listening" || muted || !supportsTextPrompts}
                  aria-pressed={activePrompt === suggestion.prompt}
                  onClick={() => sendPrompt(suggestion.prompt)}
                >
                  <Sparkles size={13} aria-hidden="true" />
                  {suggestion.prompt}
                </button>
              ))}
            </div>
          </div>
        </section>

        <aside className={styles.detailsPanel} aria-label="Session context">
          <div className={styles.contextHeading}>
            <div className={styles.customerAvatar}>{profile.initials}</div>
            <div>
              <span>Your profile</span>
              <strong>{profile.fullName}</strong>
            </div>
            <span className={styles.verified} aria-label="Verified customer">
              <Check size={13} strokeWidth={2.4} />
            </span>
          </div>

          <div className={styles.contextGrid}>
            <div>
              <span>Plan</span>
              <strong>{profile.planName}</strong>
            </div>
            <div>
              <span>Language</span>
              <strong>{profile.preferredLanguage}</strong>
            </div>
          </div>

          <details className={styles.disclosure} open>
            <summary>
              <span>{isDemo ? "Demo transcript" : "Live transcript"}</span>
              <ChevronDown size={16} aria-hidden="true" />
            </summary>
            <div
              ref={transcriptRef}
              className={styles.transcript}
              role="log"
              aria-label="Conversation transcript"
              tabIndex={0}
              onScroll={(event) => {
                const element = event.currentTarget;
                const nearBottom = isNearTranscriptBottom(element.scrollTop, element.scrollHeight, element.clientHeight);
                followTranscriptRef.current = nearBottom;
                setReadingHistory(!nearBottom);
              }}
              aria-live="polite"
              aria-relevant="additions"
            >
              {transcript.length === 0 ? (
                <p className={styles.emptyTranscript}>Your conversation will appear here once the session begins.</p>
              ) : (
                transcript.map((item) => (
                  <div className={styles.transcriptItem} key={item.id}>
                    <span data-speaker={item.speaker}>{item.speaker === "Svara" ? profile.agentName : item.speaker}</span>
                    <p>{item.text}</p>
                  </div>
                ))
              )}
              {voiceState === "thinking" && (
                <div className={styles.typing} aria-label={`${profile.agentName} is preparing a response`}>
                  <i />
                  <i />
                  <i />
                </div>
              )}
            </div>
            {readingHistory && (
              <button type="button" className={styles.jumpToLatest} onClick={() => {
                followTranscriptRef.current = true;
                setReadingHistory(false);
                if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
              }}>
                Jump to latest
              </button>
            )}
          </details>

          <details className={styles.disclosure}>
            <summary>
              <span>Shared context</span>
              <ChevronDown size={16} aria-hidden="true" />
            </summary>
            <div className={styles.contextDetails}>
              <div>
                <span>Workspace</span>
                <strong>{profile.workspaceName}</strong>
              </div>
              <div>
                <span>Data scope</span>
                <strong>Verified profile</strong>
              </div>
              <p>
                Only the information needed to answer this conversation is shared with the assistant.
              </p>
            </div>
          </details>

          <div className={styles.privacyNote}>
            <ShieldCheck size={18} strokeWidth={1.7} />
            <div>
              <strong>Context protected</strong>
              <span>Identity and account access stay controlled by your secure session.</span>
            </div>
          </div>

          {voiceState === "ended" && lastAgentMessage && (
            <button type="button" className={styles.clearButton} onClick={resetSession}>
              Clear this session
            </button>
          )}
        </aside>
      </div>

      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announcedStatus}
      </p>
    </div>
  );
}

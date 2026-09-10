import type { VoiceSessionResponse } from "@/lib/api-types";

const LIVE_AUDIO_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

export function voiceTransportRequiresMicrophone(
  transport: VoiceSessionResponse["connection"]["transport"],
) {
  return transport === "websocket";
}

export async function acquireMicrophoneForTransport(
  transport: VoiceSessionResponse["connection"]["transport"],
  mediaDevices: Pick<MediaDevices, "getUserMedia"> | undefined =
    typeof navigator === "undefined" ? undefined : navigator.mediaDevices,
) {
  if (!voiceTransportRequiresMicrophone(transport)) return null;
  if (!mediaDevices?.getUserMedia) {
    throw new Error("Microphone access is not supported in this browser.");
  }
  return mediaDevices.getUserMedia(LIVE_AUDIO_CONSTRAINTS);
}

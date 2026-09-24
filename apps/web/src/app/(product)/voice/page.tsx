import { VoiceSession } from "@/components/voice-session";
import { getCurrentProfile } from "@/lib/server-api";
import { redirect } from "next/navigation";

export default async function VoicePage() {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role === "admin") redirect("/customers");

  return (
    <VoiceSession
      profile={{
        firstName: profile.first_name,
        fullName: profile.full_name,
        initials: profile.initials,
        workspaceName: profile.workspace_name,
        planName: profile.plan_name ?? "Not assigned",
        preferredLanguage: profile.preferred_language ?? "Not set",
        agentName: profile.agent_name ?? "Your assistant",
        openingMessage: profile.agent_opening_message ?? "Hello, how can I help you today?",
        isDemo: profile.voice_mode === "mock",
      }}
    />
  );
}

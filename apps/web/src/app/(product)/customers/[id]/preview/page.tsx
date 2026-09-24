import { notFound, redirect } from "next/navigation";

import { VoiceSession } from "@/components/voice-session";
import {
  FALLBACK_AGENT_OPENING_MESSAGE,
  renderAgentOpeningTemplate,
} from "@/lib/api-validation";
import { BackendApiError, getCurrentProfile, getCustomer } from "@/lib/server-api";

export default async function CustomerVoicePreviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role !== "admin") redirect("/dashboard");

  const { id } = await params;
  let customer;
  try {
    customer = await getCustomer(id);
  } catch (error) {
    if (error instanceof BackendApiError && (error.status === 400 || error.status === 404)) notFound();
    throw error;
  }
  if (!customer) redirect("/sign-in");
  if (!customer.is_active) redirect(`/customers/${encodeURIComponent(customer.id)}`);

  const firstName = customer.full_name.trim().split(/\s+/, 1)[0] || "there";
  const renderedOpening = renderAgentOpeningTemplate(
    customer.agent_configuration.opening_message,
    firstName,
  );

  return (
    <VoiceSession
      mode="admin-preview"
      returnHref={`/customers/${encodeURIComponent(customer.id)}`}
      sessionEndpoint={`/api/customers/${encodeURIComponent(customer.id)}/voice-preview-sessions`}
      profile={{
        firstName,
        fullName: customer.full_name,
        initials: customer.initials,
        workspaceName: profile.workspace_name,
        planName: customer.plan_name,
        preferredLanguage: customer.preferred_language,
        agentName: customer.agent_configuration.display_name,
        openingMessage: renderedOpening.valid
          ? renderedOpening.rendered
          : FALLBACK_AGENT_OPENING_MESSAGE,
        isDemo: profile.voice_mode === "mock",
      }}
    />
  );
}

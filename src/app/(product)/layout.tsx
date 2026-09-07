import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { EditorDraftProvider } from "@/components/editor-drafts";
import { getCurrentProfile } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ProductLayout({ children }: { children: React.ReactNode }) {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");

  return (
    <EditorDraftProvider key={profile.user_id}>
      <AppShell
        profile={{
          full_name: profile.full_name,
          initials: profile.initials,
          workspace_name: profile.workspace_name,
          role: profile.role,
        }}
      >
        {children}
      </AppShell>
    </EditorDraftProvider>
  );
}

import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { EditorDraftProvider } from "@/components/editor-drafts";
import { getCurrentProfile } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ProductLayout({ children }: { children: React.ReactNode }) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  const profile = await getCurrentProfile();
  if (!profile) redirect("/access-pending");

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

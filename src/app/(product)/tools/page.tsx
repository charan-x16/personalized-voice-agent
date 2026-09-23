import { Blocks, RadioTower } from "lucide-react";
import { redirect } from "next/navigation";

import { ToolRegistry } from "@/components/tool-registry";
import { getCurrentProfile, getVoiceTools } from "@/lib/server-api";
import styles from "./tools.module.css";

export default async function ToolsPage() {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role !== "admin") redirect("/dashboard");
  const tools = await getVoiceTools();
  if (!tools) redirect("/sign-in");

  return (
    <div className={styles.workspace}>
      <header className={styles.header}>
        <div>
          <p className="eyebrow">Conversation infrastructure</p>
          <h1 className="display-type">Tools your agents can trust.</h1>
          <p>
            Connect Sarvam conversations to approved Svara capabilities, then decide which
            customers can use each one.
          </p>
        </div>
        <div className={styles.flow} aria-label="Runtime flow">
          <RadioTower size={18} aria-hidden="true" />
          <span>Sarvam</span><i aria-hidden="true" />
          <Blocks size={18} aria-hidden="true" />
          <span>Svara backend</span>
        </div>
      </header>
      <ToolRegistry initial={tools} />
      <footer className={styles.note}>
        Tool secrets stay in Sarvam and Svara. Customer requests are resolved from the active
        conversation reference; tenant or customer IDs are never accepted from the model.
      </footer>
    </div>
  );
}

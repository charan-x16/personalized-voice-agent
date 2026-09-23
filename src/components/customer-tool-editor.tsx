"use client";

import { LockKeyhole, Power, Wrench } from "lucide-react";
import { useState } from "react";

import type { CustomerVoiceTool, CustomerVoiceToolListResponse } from "@/lib/api-types";
import { parseCustomerVoiceToolResponse } from "@/lib/api-validation";
import styles from "./customer-tool-editor.module.css";

async function responseError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (typeof payload === "object" && payload !== null && "detail" in payload && typeof payload.detail === "string") return payload.detail;
  } catch {}
  return "Could not update customer tool access.";
}

export function CustomerToolEditor({ initial }: { initial: CustomerVoiceToolListResponse }) {
  const [items, setItems] = useState(initial.items);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function setEnabled(item: CustomerVoiceTool, enabled: boolean) {
    if (pendingId || !item.tool.is_enabled) return;
    setPendingId(item.tool.id);
    setError(null);
    try {
      const response = await fetch(
        `/api/tools/customer-assignments/${encodeURIComponent(initial.customer_id)}/${encodeURIComponent(item.tool.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            is_enabled: enabled,
            expected_revision: item.revision,
          }),
        },
      );
      if (!response.ok) throw new Error(await responseError(response));
      const updated = parseCustomerVoiceToolResponse(await response.json());
      if (!updated) throw new Error("The tool service returned an invalid response.");
      setItems((current) => current.map((value) => value.tool.id === updated.tool.id ? updated : value));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update customer tool access.");
    } finally {
      setPendingId(null);
    }
  }

  const enabledCount = items.filter((item) => item.tool.is_enabled && item.is_enabled).length;

  return (
    <section className={styles.panel} aria-labelledby="customer-tools-title">
      <header className={styles.header}>
        <div className={styles.headingIcon}><Wrench size={19} aria-hidden="true" /></div>
        <div>
          <p className="eyebrow">Conversation capabilities</p>
          <h2 id="customer-tools-title">Customer tools</h2>
          <p>{enabledCount} of {items.length} approved tools available during this customer&apos;s calls.</p>
        </div>
        <span className={styles.scoped}><LockKeyhole size={14} aria-hidden="true" /> Session scoped</span>
      </header>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <div className={styles.list}>
        {items.map((item) => {
          const unavailable = !item.tool.is_enabled;
          const checked = item.is_enabled && !unavailable;
          return (
            <div className={styles.row} key={item.tool.id}>
              <div>
                <strong>{item.tool.display_name}</strong>
                <p>{item.tool.description}</p>
                <code>{item.tool.tool_key}</code>
              </div>
              <label className={`${styles.switch} ${checked ? styles.switchOn : ""} ${unavailable ? styles.switchUnavailable : ""}`}>
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={pendingId !== null || unavailable}
                  onChange={(event) => setEnabled(item, event.target.checked)}
                />
                <span aria-hidden="true"><i /></span>
                <b>{pendingId === item.tool.id ? "Saving…" : unavailable ? "Workspace disabled" : checked ? "Available" : "Not available"}</b>
              </label>
            </div>
          );
        })}
        {!items.length && <div className={styles.empty}><Power size={20} aria-hidden="true" /><strong>No tools registered</strong><p>Add an approved capability from the Agent tools page first.</p></div>}
      </div>
    </section>
  );
}

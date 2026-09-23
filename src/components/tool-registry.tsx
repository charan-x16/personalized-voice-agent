"use client";

import { Check, Copy, History, Plus, Power, ShieldCheck, Wrench } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import type {
  VoiceToolCapability,
  VoiceToolAdminEvent,
  VoiceToolDefinition,
  VoiceToolListResponse,
} from "@/lib/api-types";
import {
  parseVoiceToolDefinitionResponse,
  parseVoiceToolListResponse,
} from "@/lib/api-validation";
import styles from "./tool-registry.module.css";

const capabilities: Array<{
  value: VoiceToolCapability;
  label: string;
  key: string;
  description: string;
  mode: "Read" | "Write";
}> = [
  { value: "customer_profile", label: "Customer profile", key: "get_customer_profile", description: "Verified name, language, and plan", mode: "Read" },
  { value: "order_status", label: "Order status", key: "get_order_status", description: "Customer-scoped order lookup", mode: "Read" },
  { value: "reservation_availability", label: "Table availability", key: "check_availability", description: "Real-time table and time lookup", mode: "Read" },
  { value: "reservation_lookup", label: "Reservation lookup", key: "find_reservation", description: "Upcoming customer reservations", mode: "Read" },
  { value: "reservation_create", label: "Create reservation", key: "create_reservation", description: "Book a confirmed available time", mode: "Write" },
  { value: "reservation_reschedule", label: "Reschedule reservation", key: "reschedule_reservation", description: "Move an existing reservation", mode: "Write" },
  { value: "reservation_cancel", label: "Cancel reservation", key: "cancel_reservation", description: "Cancel a confirmed reservation", mode: "Write" },
];

const eventTime = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
  timeZoneName: "short",
});

function eventDescription(event: VoiceToolAdminEvent): string {
  if (event.action === "voice_tool.created") return "registered this approved tool";
  if (event.action === "customer_voice_tool.updated") {
    return `updated access for ${event.customer_reference ?? "a customer"}`;
  }
  return `updated ${event.changed_fields.map((field) => field.replaceAll("_", " ")).join(", ")}`;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (typeof payload === "object" && payload !== null && "detail" in payload && typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {}
  return "The tool service could not complete this request.";
}

export function ToolRegistry({ initial }: { initial: VoiceToolListResponse }) {
  const [tools, setTools] = useState(initial.items);
  const [events, setEvents] = useState(initial.recent_events);
  const [showCreate, setShowCreate] = useState(false);
  const [capability, setCapability] = useState<VoiceToolCapability>("customer_profile");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const selected = useMemo(
    () => capabilities.find((item) => item.value === capability) ?? capabilities[0],
    [capability],
  );

  async function refreshRegistry() {
    try {
      const response = await fetch("/api/tools", { cache: "no-store" });
      if (!response.ok) return;
      const refreshed = parseVoiceToolListResponse(await response.json());
      if (!refreshed) return;
      setTools(refreshed.items);
      setEvents(refreshed.recent_events);
    } catch {
      // The mutation already succeeded; retain the immediate local update.
    }
  }

  async function toggleTool(tool: VoiceToolDefinition) {
    if (pendingId) return;
    setPendingId(tool.id);
    setError(null);
    try {
      const response = await fetch(`/api/tools/${encodeURIComponent(tool.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: tool.revision,
          is_enabled: !tool.is_enabled,
        }),
      });
      if (!response.ok) throw new Error(await errorDetail(response));
      const updated = parseVoiceToolDefinitionResponse(await response.json());
      if (!updated) throw new Error("The tool service returned an invalid response.");
      setTools((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      await refreshRegistry();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update the tool.");
    } finally {
      setPendingId(null);
    }
  }

  async function createTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating) return;
    const form = new FormData(event.currentTarget);
    setCreating(true);
    setError(null);
    try {
      const response = await fetch("/api/tools", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_key: String(form.get("tool_key") ?? ""),
          display_name: String(form.get("display_name") ?? ""),
          description: String(form.get("description") ?? ""),
          capability,
          is_enabled: true,
        }),
      });
      if (!response.ok) throw new Error(await errorDetail(response));
      const created = parseVoiceToolDefinitionResponse(await response.json());
      if (!created) throw new Error("The tool service returned an invalid response.");
      setTools((current) => [...current, created]);
      setShowCreate(false);
      await refreshRegistry();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the tool.");
    } finally {
      setCreating(false);
    }
  }

  async function copyEndpoint(tool: VoiceToolDefinition) {
    await navigator.clipboard.writeText(`/v1/sarvam/tools/execute/${tool.tool_key}`);
    setCopiedId(tool.id);
    window.setTimeout(() => setCopiedId((value) => (value === tool.id ? null : value)), 1600);
  }

  return (
    <>
      <section className={styles.summary} aria-label="Tool registry summary">
        <div><span>Registered</span><strong>{tools.length}</strong></div>
        <div><span>Available</span><strong>{tools.filter((tool) => tool.is_enabled).length}</strong></div>
        <div><span>Customer links</span><strong>{tools.reduce((sum, tool) => sum + tool.assigned_customer_count, 0)}</strong></div>
        <div className={styles.safety}><ShieldCheck size={18} aria-hidden="true" /><p><strong>Allow-listed execution</strong><span>No arbitrary outbound URLs or customer-selected code</span></p></div>
      </section>

      <section className={styles.registry} aria-labelledby="tool-registry-title">
        <header className={styles.registryHeader}>
          <div><p className="eyebrow">Approved capabilities</p><h2 id="tool-registry-title">Tool registry</h2></div>
          <button className={styles.createButton} type="button" onClick={() => setShowCreate((value) => !value)} aria-expanded={showCreate}>
            <Plus size={16} aria-hidden="true" /> Add tool
          </button>
        </header>

        {showCreate && (
          <form className={styles.createPanel} onSubmit={createTool}>
            <div className={styles.formHeading}><Wrench size={18} aria-hidden="true" /><div><strong>Register an approved tool</strong><span>Choose business logic already protected by Svara.</span></div></div>
            <label>Capability<select value={capability} onChange={(event) => setCapability(event.target.value as VoiceToolCapability)}>{capabilities.map((item) => <option value={item.value} key={item.value}>{item.label} · {item.mode}</option>)}</select></label>
            <label>Tool key<input name="tool_key" key={selected.key} defaultValue={selected.key} pattern="[a-z][a-z0-9_]{2,79}" maxLength={80} required /></label>
            <label>Display name<input name="display_name" key={selected.label} defaultValue={selected.label} maxLength={80} required /></label>
            <label className={styles.descriptionField}>Description<textarea name="description" key={selected.description} defaultValue={selected.description} maxLength={500} required /></label>
            <div className={styles.formActions}><button type="button" onClick={() => setShowCreate(false)}>Cancel</button><button type="submit" disabled={creating}>{creating ? "Creating…" : "Create tool"}</button></div>
          </form>
        )}

        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.toolList}>
          {!tools.length && (
            <div className={styles.emptyState}>
              <Wrench size={22} aria-hidden="true" />
              <h3>Your registry is ready</h3>
              <p>Add an approved capability, then assign it from a customer profile.</p>
              <button type="button" onClick={() => setShowCreate(true)}>Add the first tool</button>
            </div>
          )}
          {tools.map((tool, index) => {
            const metadata = capabilities.find((item) => item.value === tool.capability);
            return (
              <article className={styles.toolRow} key={tool.id}>
                <span className={styles.index} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                <div className={styles.toolCopy}>
                  <div className={styles.toolTitle}><h3>{tool.display_name}</h3><span className={metadata?.mode === "Write" ? styles.writeBadge : styles.readBadge}>{metadata?.mode ?? "Read"}</span></div>
                  <p>{tool.description}</p>
                  <button className={styles.endpoint} type="button" onClick={() => copyEndpoint(tool)} title="Copy endpoint path">
                    <code>/v1/sarvam/tools/execute/{tool.tool_key}</code>{copiedId === tool.id ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                  </button>
                </div>
                <div className={styles.toolMeta}><span>{tool.assigned_customer_count} customer{tool.assigned_customer_count === 1 ? "" : "s"}</span><span>rev. {tool.revision}</span></div>
                <button className={`${styles.powerButton} ${tool.is_enabled ? styles.powerOn : ""}`} type="button" disabled={pendingId !== null} onClick={() => toggleTool(tool)} aria-label={`${tool.is_enabled ? "Disable" : "Enable"} ${tool.display_name}`}>
                  <Power size={15} aria-hidden="true" /> {pendingId === tool.id ? "Saving…" : tool.is_enabled ? "Available" : "Disabled"}
                </button>
              </article>
            );
          })}
        </div>
      </section>

      <section className={styles.activity} aria-labelledby="tool-activity-title">
        <header className={styles.activityHeader}>
          <div className={styles.activityTitle}>
            <History size={18} aria-hidden="true" />
            <div>
              <p className="eyebrow">Append-only audit</p>
              <h2 id="tool-activity-title">Recent changes</h2>
            </div>
          </div>
          <span>Latest {events.length} events</span>
        </header>
        {events.length ? (
          <ol className={styles.eventList}>
            {events.map((event) => (
              <li key={event.id}>
                <span className={styles.eventMark} aria-hidden="true" />
                <div className={styles.eventCopy}>
                  <p><strong>{event.actor_display_name}</strong> {eventDescription(event)}.</p>
                  <span>{event.tool_display_name} · revision {event.revision}</span>
                </div>
                <time dateTime={event.created_at}>{eventTime.format(new Date(event.created_at))}</time>
              </li>
            ))}
          </ol>
        ) : (
          <div className={styles.noEvents}>
            <History size={20} aria-hidden="true" />
            <p>Administrative tool changes will appear here.</p>
          </div>
        )}
      </section>
    </>
  );
}

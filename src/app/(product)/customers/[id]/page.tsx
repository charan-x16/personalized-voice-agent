import {
  ArrowLeft,
  Bot,
  CalendarDays,
  Clock3,
  Database,
  History,
  Languages,
  LockKeyhole,
  MessageSquareText,
  PackageCheck,
  ReceiptText,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AgentConfigurationEditor } from "@/components/agent-configuration-editor";
import { CustomerEditor } from "@/components/customer-editor";
import { BackendApiError, getCurrentProfile, getCustomer } from "@/lib/server-api";
import {
  conversationPreview,
  conversationTitle,
  outcomeLabel,
  type OutcomeLabel,
} from "@/utils/conversation";
import styles from "../customers.module.css";

function formatDate(value: string, withTime = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(date);
}

function formatDuration(totalSeconds: number | null) {
  if (totalSeconds === null) return "—";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function outcomeClass(outcome: OutcomeLabel) {
  if (outcome === "Resolved") return styles.outcomeResolved;
  if (outcome === "Follow-up") return styles.outcomeFollowUp;
  return styles.outcomeEscalated;
}

const auditFieldLabels: Record<string, string> = {
  display_name: "Agent name",
  full_name: "Full name",
  instructions: "Custom instructions",
  is_active: "Profile status",
  opening_message: "Opening message",
  plan_name: "Plan",
  preferred_language: "Language",
  tone: "Conversation tone",
};

function auditActionLabel(action: string) {
  if (action === "customer.agent_configuration_updated") return "Agent configuration updated";
  return "Customer profile updated";
}

function auditFields(fields: string[]) {
  if (!fields.length) return "No field names recorded";
  return fields.map((field) => auditFieldLabels[field] ?? field.replaceAll("_", " ")).join(", ");
}

export default async function CustomerDetailPage({
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

  const resolvedRate = customer.conversation_count
    ? `${Math.round(
        (customer.resolved_conversation_count / customer.conversation_count) * 100,
      )}%`
    : "—";
  const customerFirstName = customer.full_name.trim().split(/\s+/, 1)[0] || "there";

  return (
    <div className={styles.workspace}>
      <Link href="/customers" className={styles.backLink}>
        <ArrowLeft size={16} strokeWidth={1.8} aria-hidden="true" /> All customers
      </Link>

      <header className={styles.detailHeader}>
        <div className={styles.detailIdentity}>
          <span className={styles.detailAvatar} aria-hidden="true">{customer.initials}</span>
          <div>
            <p className="eyebrow">Customer profile</p>
            <h1 className={`${styles.detailTitle} display-type`}>{customer.full_name}</h1>
            <p className={styles.detailReference}>Reference {customer.external_ref}</p>
          </div>
        </div>
        <span className={`${styles.status} ${styles.detailHeaderStatus} ${customer.is_active ? styles.active : styles.inactive}`}>
          <span aria-hidden="true" />
          {customer.is_active ? "Profile active" : "Profile inactive"}
        </span>
      </header>

      <dl className={styles.detailMeta}>
        <div>
          <dt><Languages size={15} strokeWidth={1.8} aria-hidden="true" /> Preferred language</dt>
          <dd>{customer.preferred_language}</dd>
        </div>
        <div>
          <dt><PackageCheck size={15} strokeWidth={1.8} aria-hidden="true" /> Customer plan</dt>
          <dd>{customer.plan_name}</dd>
        </div>
        <div>
          <dt><ReceiptText size={15} strokeWidth={1.8} aria-hidden="true" /> Open orders</dt>
          <dd>{customer.open_order_count}</dd>
        </div>
        <div>
          <dt><MessageSquareText size={15} strokeWidth={1.8} aria-hidden="true" /> Conversations</dt>
          <dd>{customer.conversation_count} total · {resolvedRate} resolved</dd>
        </div>
      </dl>

      <nav className={styles.detailSectionNav} aria-label="Customer profile sections">
        <a href="#profile-settings">Profile</a>
        <a href="#agent-settings">Agent</a>
        <a href="#admin-changes">Changes</a>
        <a href="#customer-activity">Activity</a>
      </nav>

      <div className={styles.detailGrid}>
        <div className={styles.profileEditorSlot} id="profile-settings">
          <CustomerEditor
            key={`${customer.id}:${customer.profile_revision}`}
            customer={customer}
          />
        </div>

        <aside className={styles.profileAside}>
          <section className={styles.contextCard} aria-labelledby="stored-context-title">
            <div className={styles.cardHeading}>
              <div>
                <p className="eyebrow">Verified data</p>
                <h2 id="stored-context-title">Stored context</h2>
              </div>
              <Database size={18} strokeWidth={1.7} aria-hidden="true" />
            </div>
            <dl className={styles.contextList}>
              <div>
                <dt>Email</dt>
                <dd title={customer.email ?? undefined}>{customer.email ?? "Not provided"}</dd>
              </div>
              <div>
                <dt>External reference</dt>
                <dd>{customer.external_ref}</dd>
              </div>
              <div>
                <dt>Customer since</dt>
                <dd>{formatDate(customer.created_at)}</dd>
              </div>
              <div>
                <dt>Resolved outcomes</dt>
                <dd>{customer.resolved_conversation_count} ({resolvedRate})</dd>
              </div>
              <div>
                <dt>Profile revision</dt>
                <dd>{customer.profile_revision}</dd>
              </div>
            </dl>
          </section>

          <section className={styles.privacyCard} aria-label="Customer data boundary">
            <LockKeyhole size={18} strokeWidth={1.7} aria-hidden="true" />
            <div>
              <strong>Protected customer boundary</strong>
              <p>
                This profile is loaded from your backend and scoped to {profile.workspace_name}.
                A voice provider receives only the approved context needed for a session.
              </p>
            </div>
          </section>
        </aside>
      </div>

      <div className={styles.agentConfigurationSection} id="agent-settings">
        <AgentConfigurationEditor
          key={`${customer.id}:${customer.agent_configuration.revision}`}
          customerId={customer.id}
          customerFirstName={customerFirstName}
          configuration={customer.agent_configuration}
        />
      </div>

      <section className={styles.auditSection} id="admin-changes" aria-labelledby="customer-audit-title">
        <div className={styles.auditHeading}>
          <div>
            <p className="eyebrow">Accountability</p>
            <h2 id="customer-audit-title">Recent admin changes</h2>
          </div>
          <p className={styles.auditNote}>
            <History size={15} strokeWidth={1.75} aria-hidden="true" />
            Up to 10 recent append-only application events; not complete history or provider logs
          </p>
        </div>

        <div className={styles.auditPanel}>
          {customer.recent_audit_events.length ? (
            <ol className={styles.auditList}>
              {customer.recent_audit_events.map((event) => {
                const isAgentEvent = event.action === "customer.agent_configuration_updated";
                return (
                  <li className={styles.auditEvent} key={event.id}>
                    <span className={styles.auditIcon} aria-hidden="true">
                      {isAgentEvent ? (
                        <Bot size={16} strokeWidth={1.7} aria-hidden="true" />
                      ) : (
                        <UserRound size={16} strokeWidth={1.7} aria-hidden="true" />
                      )}
                    </span>
                    <div className={styles.auditBody}>
                      <div className={styles.auditTopline}>
                        <strong>{auditActionLabel(event.action)}</strong>
                        <time dateTime={event.created_at}>{formatDate(event.created_at, true)}</time>
                      </div>
                      <p>{auditFields(event.changed_fields)}</p>
                      <small>{event.actor_display_name} · revision {event.revision}</small>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <div className={styles.auditEmpty}>
              <History size={20} strokeWidth={1.7} aria-hidden="true" />
              <h3>No admin changes recorded</h3>
              <p>Profile and agent updates made in this application will appear here.</p>
            </div>
          )}
        </div>
      </section>

      <section className={styles.activitySection} id="customer-activity" aria-labelledby="recent-customer-activity">
        <div className={styles.activitySectionHeading}>
          <div>
            <p className="eyebrow">Voice history</p>
            <h2 id="recent-customer-activity">Recent activity</h2>
          </div>
          <span>Latest {customer.recent_conversations.length} of {customer.conversation_count} · summary view</span>
        </div>

        <div className={styles.activityPanel}>
          {customer.recent_conversations.length ? (
            customer.recent_conversations.map((conversation) => {
              const outcome = outcomeLabel(conversation.resolution);
              return (
                <article className={styles.activityRow} key={conversation.id}>
                  <span className={styles.activityIcon} aria-hidden="true">
                    <UserRound size={17} strokeWidth={1.75} aria-hidden="true" />
                  </span>
                  <span className={styles.activityCopy}>
                    <strong>{conversationTitle(conversation.resolution)}</strong>
                    <small>{conversationPreview(conversation.summary)}</small>
                  </span>
                  <span className={styles.activityWhen}>
                    <strong>{formatDate(conversation.started_at, true)}</strong>
                    <span>{formatDuration(conversation.duration_seconds)} · {conversation.language}</span>
                  </span>
                  <span className={`${styles.activityOutcome} ${outcomeClass(outcome)}`}>{outcome}</span>
                </article>
              );
            })
          ) : (
            <div className={styles.activityEmpty}>
              <Clock3 size={20} strokeWidth={1.7} aria-hidden="true" />
              <h3>No voice activity yet</h3>
              <p>The first completed conversation for this customer will appear here.</p>
            </div>
          )}
        </div>
      </section>

      <footer className={styles.directoryFootnote}>
        <CalendarDays size={15} strokeWidth={1.8} aria-hidden="true" />
        Profile created {formatDate(customer.created_at)}
      </footer>
    </div>
  );
}

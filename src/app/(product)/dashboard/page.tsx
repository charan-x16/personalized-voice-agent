import {
  ArrowRight,
  AudioLines,
  Check,
  Clock3,
  Languages,
  MessageCircleMore,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import type { ConversationSummary } from "@/lib/api-types";
import { getConversations, getCurrentProfile } from "@/lib/server-api";
import { LocalTime } from "@/components/local-time";
import {
  conversationPreview,
  conversationTitle,
  formatAverageDuration,
  formatDuration,
  outcomeLabel,
  type OutcomeLabel,
} from "@/utils/conversation";
import styles from "../workspace.module.css";

const signalBars = [18, 29, 42, 26, 53, 68, 37, 57, 75, 48, 33, 61, 44, 27, 18];

function outcomeClass(outcome: OutcomeLabel) {
  if (outcome === "Resolved") return styles.resolved;
  if (outcome === "Follow-up") return styles.followUp;
  return styles.escalated;
}

function buildMetrics(conversations: ConversationSummary[], planName: string, total: number) {
  const resolvedCount = conversations.filter(
    (conversation) => outcomeLabel(conversation.resolution) === "Resolved",
  ).length;
  const durations = conversations.flatMap((conversation) =>
    conversation.duration_seconds === null ? [] : [conversation.duration_seconds],
  );
  const averageSeconds = durations.length
    ? Math.round(durations.reduce((total, duration) => total + duration, 0) / durations.length)
    : 0;
  const resolvedRate = conversations.length
    ? `${Math.round((resolvedCount / conversations.length) * 100)}%`
    : "—";

  return [
    { label: "Conversations", value: String(total), note: "All saved outcomes" },
    { label: "Resolved", value: resolvedRate, note: conversations.length ? `${resolvedCount} of latest ${conversations.length}` : "No outcomes yet" },
    {
      label: "Avg. duration",
      value: durations.length ? formatAverageDuration(averageSeconds) : "—",
      note: conversations.length ? `Latest ${conversations.length} saved calls` : "No completed calls yet",
    },
    { label: "Customer plan", value: planName, note: "Verified profile" },
  ];
}

export default async function DashboardPage() {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role === "admin") redirect("/customers");
  const conversationData = await getConversations();
  if (!conversationData) redirect("/sign-in");
  const now = new Date();
  const conversations = conversationData.items;
  const metrics = buildMetrics(conversations, profile.plan_name ?? "Not assigned", conversationData.total);

  return (
    <div className={styles.workspace}>
      <header className={`${styles.pageHeader} reveal`}>
        <div>
          <p className="eyebrow">Workspace overview</p>
          <h1 className={`${styles.pageTitle} display-type`}>
            Welcome back, {profile.first_name}.
          </h1>
          <p className={styles.pageIntro}>
            Your conversations, customer context, and assistant—all in one place.
          </p>
        </div>
        <p className={styles.dateline}><LocalTime value={now.toISOString()} kind="day" /></p>
      </header>

      <section className={`${styles.heroGrid} reveal reveal-delay-1`} aria-label="Voice agent overview">
        <article className={styles.voiceCard}>
          <div className={styles.voiceCardCopy}>
            <div className={styles.readyLabel}>
              <span className={styles.liveDot} aria-hidden="true" />
              {profile.voice_mode === "mock" ? "Demo workspace" : "Your voice workspace"}
            </div>
            <div>
              <p className={styles.voiceKicker}>Your personal voice assistant</p>
              <h2 className={styles.voiceTitle}>A conversation is one breath away.</h2>
              <p className={styles.voiceDescription}>
                {profile.voice_mode === "mock" ? "Explore a text-based demo using your customer profile. No live voice audio is sent." : "Connect with your assistant using your verified customer profile."}
              </p>
            </div>
            <Link href="/voice" className={styles.startButton}>
              <span className={styles.startButtonIcon} aria-hidden="true">
                <AudioLines size={18} strokeWidth={2} />
              </span>
              Start a conversation
              <ArrowRight size={17} strokeWidth={1.8} />
            </Link>
          </div>

          <div className={styles.voiceArtwork} aria-hidden="true">
            <span className={styles.orbitOne} />
            <span className={styles.orbitTwo} />
            <div className={styles.signal}>
              {signalBars.map((height, index) => (
                <span key={`${height}-${index}`} style={{ height }} />
              ))}
            </div>
          </div>
        </article>

        <aside className={styles.agentCard}>
          <div className={styles.sectionTopline}>
            <p className="eyebrow">Your assistant</p>
            <span className={styles.livePill}>{profile.voice_mode === "mock" ? "Demo" : "Configured"}</span>
          </div>

          <div className={styles.agentIdentity}>
            <div className={styles.agentMark} aria-hidden="true">
              <Sparkles size={22} strokeWidth={1.65} />
            </div>
            <div>
              <h2>{profile.agent_name ?? "Your assistant"}</h2>
              <p>{profile.workspace_name}</p>
            </div>
          </div>

          <dl className={styles.agentDetails}>
            <div>
              <dt><Languages size={15} /> Language</dt>
              <dd>{profile.preferred_language ?? "Not set"}</dd>
            </div>
            <div>
              <dt><MessageCircleMore size={15} /> Mode</dt>
              <dd>{profile.voice_mode === "mock" ? "Text-only demo" : "Voice session"}</dd>
            </div>
            <div>
              <dt><Clock3 size={15} /> Last saved</dt>
              <dd>{conversations[0] ? <LocalTime value={conversations[0].started_at} /> : "No calls yet"}</dd>
            </div>
          </dl>

          <div className={styles.agentFoot}>
            <span><Check size={14} strokeWidth={2.2} /> Customer context connected</span>
          </div>
        </aside>
      </section>

      <section className={`${styles.metricsPanel} reveal reveal-delay-2`} aria-labelledby="performance-title">
        <div className={styles.metricsHeading}>
          <p className="eyebrow" id="performance-title">Recorded activity</p>
          <span>Authenticated customer scope</span>
        </div>
        <dl className={styles.metricsGrid}>
          {metrics.map((metric) => (
            <div className={styles.metric} key={metric.label}>
              <dt>{metric.label}</dt>
              <dd>{metric.value}</dd>
              <span>{metric.note}</span>
            </div>
          ))}
        </dl>
      </section>

      <section className={`${styles.recentSection} reveal reveal-delay-3`} aria-labelledby="recent-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className="eyebrow">Activity</p>
            <h2 id="recent-title">Recent conversations</h2>
          </div>
          <Link href="/conversations" className={styles.textLink}>
            View all <ArrowRight size={15} />
          </Link>
        </div>

        {conversations.length ? (
          <div className={styles.conversationList}>
            {conversations.slice(0, 3).map((conversation) => {
              const outcome = outcomeLabel(conversation.resolution);
              return (
                <Link
                  href={`/conversations/${conversation.id}`}
                  className={styles.conversationRow}
                  key={conversation.id}
                  aria-label={`Open conversation: ${conversationTitle(conversation.resolution)}`}
                >
                  <span className={styles.customerAvatar} aria-hidden="true">{profile.initials}</span>
                  <span className={styles.conversationCopy}>
                    <strong>{conversationTitle(conversation.resolution)}</strong>
                    <small>{profile.full_name} · {conversationPreview(conversation.summary)}</small>
                  </span>
                  <span className={`${styles.outcome} ${outcomeClass(outcome)}`}>{outcome}</span>
                  <span className={styles.conversationTime}>
                    <strong><LocalTime value={conversation.started_at} /></strong>
                    <small>{formatDuration(conversation.duration_seconds)}</small>
                  </span>
                  <ArrowRight className={styles.rowArrow} size={17} strokeWidth={1.7} aria-hidden="true" />
                </Link>
              );
            })}
          </div>
        ) : (
          <div className={styles.recentEmpty}>
            <span aria-hidden="true"><AudioLines size={20} /></span>
            <div>
              <h3>No saved conversations yet</h3>
              <p>Complete a mock voice session and its outcome will appear here.</p>
            </div>
            <Link href="/voice" className="button button-quiet">Open voice room</Link>
          </div>
        )}
      </section>
    </div>
  );
}

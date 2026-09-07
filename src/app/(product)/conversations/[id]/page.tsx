import {
  ArrowLeft,
  AudioLines,
  CalendarDays,
  Check,
  Clock3,
  Database,
  Languages,
  LockKeyhole,
  MessageSquareText,
  Sparkles,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { BackendApiError, getConversation, getCurrentProfile } from "@/lib/server-api";
import { LocalTime } from "@/components/local-time";
import {
  conversationPreview,
  conversationTitle,
  formatDuration,
  outcomeLabel,
  shortConversationId,
  type OutcomeLabel,
} from "@/utils/conversation";
import styles from "../../workspace.module.css";

function outcomeClass(outcome: OutcomeLabel) {
  if (outcome === "Resolved") return styles.resolved;
  if (outcome === "Follow-up") return styles.followUp;
  return styles.escalated;
}

function transcriptTime(timestamp: string | null | undefined, index: number) {
  if (!timestamp) return `Turn ${String(index + 1).padStart(2, "0")}`;
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return <LocalTime value={timestamp} kind="time" />;
}

export default async function ConversationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role === "admin") redirect("/customers");

  let conversation;

  try {
    conversation = await getConversation(id);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) notFound();
    throw error;
  }

  if (!conversation) redirect("/sign-in");

  const outcome = outcomeLabel(conversation.resolution);
  const preview = conversationPreview(conversation.summary);

  return (
    <div className={`${styles.workspace} ${styles.detailWorkspace}`}>
      <Link href="/conversations" className={`${styles.backLink} reveal`}>
        <ArrowLeft size={16} strokeWidth={1.8} /> All conversations
      </Link>

      <header className={`${styles.detailHeader} reveal`}>
        <div>
          <div className={styles.detailEyebrowRow}>
            <p className="eyebrow">Conversation {shortConversationId(conversation.id)}</p>
            <span className={`${styles.outcome} ${outcomeClass(outcome)}`}>{outcome}</span>
          </div>
          <h1 className={`${styles.detailTitle} display-type`}>
            {conversationTitle(conversation.resolution)}
          </h1>
          <p>{preview}</p>
        </div>
        <Link href="/voice" className="button button-primary">
          <AudioLines size={17} /> Start another
        </Link>
      </header>

      <dl className={`${styles.detailMeta} reveal reveal-delay-1`}>
        <div>
          <dt><UserRound size={15} /> Customer</dt>
          <dd>{profile.full_name}</dd>
        </div>
        <div>
          <dt><CalendarDays size={15} /> Date</dt>
          <dd><LocalTime value={conversation.started_at} kind="datetime" /></dd>
        </div>
        <div>
          <dt><Clock3 size={15} /> Duration</dt>
          <dd>{formatDuration(conversation.duration_seconds)}</dd>
        </div>
        <div>
          <dt><Languages size={15} /> Language</dt>
          <dd>{conversation.language}</dd>
        </div>
      </dl>

      <div className={`${styles.detailGrid} reveal reveal-delay-2`}>
        <section className={styles.transcriptPanel} aria-labelledby="transcript-title">
          <div className={styles.panelHeading}>
            <div>
              <p className="eyebrow">Full conversation</p>
              <h2 id="transcript-title">Transcript</h2>
            </div>
            <span>{conversation.transcript.length} turns</span>
          </div>

          {conversation.transcript.length ? (
            <ol className={styles.transcriptList}>
              {conversation.transcript.map((turn, index) => {
                const isAgent = turn.speaker === "agent";
                const isTool = turn.speaker === "tool";
                const speakerLabel = isAgent ? "Assistant" : isTool ? "Data tool" : profile.full_name;
                return (
                  <li
                    className={`${styles.transcriptTurn} ${isAgent || isTool ? styles.agentTurn : ""}`}
                    key={`${turn.timestamp ?? "turn"}-${index}`}
                  >
                    <span className={styles.speakerMark} aria-hidden="true">
                      {isAgent ? (
                        <Sparkles size={17} strokeWidth={1.7} />
                      ) : isTool ? (
                        <Database size={16} strokeWidth={1.7} />
                      ) : (
                        profile.initials
                      )}
                    </span>
                    <div className={styles.turnBody}>
                      <div className={styles.turnMeta}>
                        <strong>{speakerLabel}</strong>
                        <span>{transcriptTime(turn.timestamp, index)}</span>
                      </div>
                      <p>{turn.text}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <div className={styles.transcriptEmpty}>
              <MessageSquareText size={21} aria-hidden="true" />
              <h3>No transcript was retained</h3>
              <p>The outcome exists, but this conversation did not include stored turns.</p>
            </div>
          )}
        </section>

        <aside className={styles.detailAside}>
          <section className={styles.summaryCard} aria-labelledby="summary-title">
            <p className="eyebrow">Outcome</p>
            <div className={styles.summaryOutcome}>
              <span className={styles.summaryCheck} aria-hidden="true"><Check size={17} /></span>
              <div>
                <h2 id="summary-title">{outcome}</h2>
                <p>{preview}</p>
              </div>
            </div>
            <dl className={styles.summaryDetails}>
              <div>
                <dt>Session type</dt>
                <dd>{conversation.provider === "mock" ? "Text-only demo" : "Voice conversation"}</dd>
              </div>
              <div>
                <dt>Provider</dt>
                <dd>{conversation.provider}</dd>
              </div>
              <div>
                <dt>Storage</dt>
                <dd>Outcome recorded</dd>
              </div>
            </dl>
          </section>

          <section className={styles.activityCard} aria-labelledby="activity-title">
            <div className={styles.sideCardHeading}>
              <div>
                <p className="eyebrow">Saved record</p>
                <h2 id="activity-title">Conversation details</h2>
              </div>
              <Database size={18} strokeWidth={1.7} aria-hidden="true" />
            </div>
            <ol className={styles.activityList}>
              <li>
                <span aria-hidden="true"><Check size={12} /></span>
                <div><strong>Private archive</strong><small>Only conversations from your profile</small></div>
              </li>
              <li>
                <span aria-hidden="true"><Check size={12} /></span>
                <div><strong>{conversation.ended_at ? "End time recorded" : "End time unavailable"}</strong><small>{conversation.provider === "mock" ? "Text-only demo" : conversation.provider}</small></div>
              </li>
              <li>
                <span aria-hidden="true"><Check size={12} /></span>
                <div><strong>Conversation saved</strong><small>Outcome persistence · complete</small></div>
              </li>
            </ol>
          </section>

          <section className={styles.privacyNote} aria-label="Data privacy information">
            <LockKeyhole size={18} strokeWidth={1.7} aria-hidden="true" />
            <div>
              <strong>Protected customer context</strong>
              <p>Account data was isolated to the customer and workspace encoded in the verified session.</p>
            </div>
          </section>
        </aside>
      </div>

      <footer className={styles.detailFootnote}>
        <MessageSquareText size={15} aria-hidden="true" />
        Transcript generated automatically. Verify important details before taking action.
      </footer>
    </div>
  );
}

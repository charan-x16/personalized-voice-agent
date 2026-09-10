import { ArrowRight, AudioLines, CalendarDays, Clock3, Search } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getConversations, getCurrentProfile } from "@/lib/server-api";
import { LocalTime } from "@/components/local-time";
import { CONVERSATION_PAGE_SIZE, MAX_CONVERSATION_PAGE, conversationArchiveHref, conversationPage } from "@/lib/conversation-query";
import {
  conversationPreview,
  conversationTitle,
  formatDuration,
  outcomeLabel,
  type OutcomeLabel,
} from "@/utils/conversation";
import styles from "../workspace.module.css";

type SearchParams = Promise<{
  query?: string | string[];
  outcome?: string | string[];
  page?: string | string[];
}>;

const filters = [
  { label: "All", value: "all" },
  { label: "Resolved", value: "resolved" },
  { label: "Follow-up", value: "follow-up" },
  { label: "Escalated", value: "escalated" },
];

function outcomeClass(outcome: OutcomeLabel) {
  if (outcome === "Resolved") return styles.resolved;
  if (outcome === "Follow-up") return styles.followUp;
  return styles.escalated;
}

export default async function ConversationsPage({ searchParams }: { searchParams: SearchParams }) {
  const [params, profile] = await Promise.all([searchParams, getCurrentProfile()]);
  if (!profile) redirect("/sign-in");
  if (profile.role === "admin") redirect("/customers");
  if (Array.isArray(params.query) || Array.isArray(params.outcome) || Array.isArray(params.page)) {
    redirect("/conversations");
  }
  const page = conversationPage(params.page);
  if (page === null || (params.query?.length ?? 0) > 200) redirect("/conversations");
  const query = params.query?.trim() ?? "";
  const activeFilter = filters.some((filter) => filter.value === params.outcome)
    ? (params.outcome ?? "all")
    : "all";
  const conversationData = await getConversations({ query, outcome: activeFilter, page });
  if (!conversationData) redirect("/sign-in");
  const filteredConversations = conversationData.items;
  const totalPages = Math.min(MAX_CONVERSATION_PAGE, Math.max(1, Math.ceil(conversationData.total / CONVERSATION_PAGE_SIZE)));
  if (page > totalPages) redirect(conversationArchiveHref(query, activeFilter, totalPages));

  function filterHref(value: string) {
    return conversationArchiveHref(query, value);
  }

  return (
    <div className={styles.workspace}>
      <header className={`${styles.pageHeader} ${styles.listPageHeader}`}>
        <div>
          <p className="eyebrow">Conversation archive</p>
          <h1 className={`${styles.pageTitle} display-type`}>Conversations</h1>
          <p className={styles.pageIntro}>
            Find a past conversation, review its outcome, and pick up where you left off.
          </p>
        </div>
        <Link href="/voice" className="button button-primary">
          <AudioLines size={17} aria-hidden="true" /> Start conversation
        </Link>
      </header>

      <section className={styles.archivePanel} aria-label="Conversation archive">
        <div className={styles.archiveToolbar}>
          <form className={styles.searchForm} action="/conversations" method="get" role="search">
            <Search size={17} strokeWidth={1.8} aria-hidden="true" />
            <label className="sr-only" htmlFor="conversation-search">Search conversations</label>
            <input
              id="conversation-search"
              name="query"
              type="search"
              autoComplete="off"
              maxLength={200}
              defaultValue={query}
              placeholder="Search summaries or outcomes…"
            />
            {activeFilter !== "all" && <input type="hidden" name="outcome" value={activeFilter} />}
            <button type="submit">Search</button>
          </form>

          <div className={styles.filterGroup} role="group" aria-label="Filter conversations by outcome">
            {filters.map((filter) => (
              <Link
                key={filter.value}
                href={filterHref(filter.value)}
                className={`${styles.filterChip} ${activeFilter === filter.value ? styles.filterChipActive : ""}`}
                aria-current={activeFilter === filter.value ? "page" : undefined}
              >
                {filter.label}
              </Link>
            ))}
          </div>
        </div>

        <div className={styles.archiveMeta}>
          <p>
            <strong>{conversationData.total}</strong>{" "}
            {conversationData.total === 1 ? "conversation" : "conversations"}
          </p>
          <span>{query || activeFilter !== "all" ? "Matching your filters" : "All saved conversations"} · newest first</span>
        </div>

        {filteredConversations.length > 0 ? (
          <div className={styles.archiveList}>
            {filteredConversations.map((conversation) => {
              const outcome = outcomeLabel(conversation.resolution);
              return (
                <Link
                  href={`/conversations/${conversation.id}`}
                  className={styles.archiveRow}
                  key={conversation.id}
                  aria-label={`View ${conversationTitle(conversation.resolution)}`}
                >
                  <span className={styles.customerAvatar} aria-hidden="true">{profile.initials}</span>

                  <span className={styles.archivePrimary}>
                    <span className={styles.archiveCustomer}>{profile.full_name}</span>
                    <strong>{conversationTitle(conversation.resolution)}</strong>
                    <small>{conversationPreview(conversation.summary)}</small>
                  </span>

                  <span className={styles.archiveDetails}>
                    <span>
                      <CalendarDays size={14} aria-hidden="true" />
                      <LocalTime value={conversation.started_at} kind="datetime" />
                    </span>
                    <span>
                      <Clock3 size={14} aria-hidden="true" />
                      {formatDuration(conversation.duration_seconds)}
                    </span>
                    <span>{conversation.language} · {conversation.provider}</span>
                  </span>

                  <span className={`${styles.outcome} ${outcomeClass(outcome)}`}>{outcome}</span>
                  <span className={styles.openRow} aria-hidden="true">
                    <ArrowRight size={17} strokeWidth={1.7} aria-hidden="true" />
                  </span>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon} aria-hidden="true"><Search size={21} /></span>
            <h2>{query || activeFilter !== "all" ? "No conversations found" : "Your archive is ready"}</h2>
            <p>
              {query || activeFilter !== "all"
                ? "Try another search term or clear the selected outcome filter."
                : "Complete a mock voice session and the saved conversation will appear here."}
            </p>
            {query || activeFilter !== "all" ? (
              <Link href="/conversations" className="button button-quiet">Clear filters</Link>
            ) : (
              <Link href="/voice" className="button button-primary">Start first conversation</Link>
            )}
          </div>
        )}
        {conversationData.total > 0 && (
          <nav className={styles.pagination} aria-label="Conversation pages">
            <p>Page {page} of {totalPages}</p>
            <div>
              {page > 1 ? <Link href={conversationArchiveHref(query, activeFilter, page - 1)}>Previous</Link> : <span aria-disabled="true">Previous</span>}
              {page < totalPages ? <Link href={conversationArchiveHref(query, activeFilter, page + 1)}>Next</Link> : <span aria-disabled="true">Next</span>}
            </div>
            {conversationData.total > MAX_CONVERSATION_PAGE * CONVERSATION_PAGE_SIZE && <p>Narrow your search to explore more results.</p>}
          </nav>
        )}
      </section>
    </div>
  );
}

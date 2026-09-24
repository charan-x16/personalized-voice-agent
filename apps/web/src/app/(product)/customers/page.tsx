import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Search,
  ShieldCheck,
  UserRoundCheck,
  UsersRound,
  UserPlus,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentProfile, getCustomers } from "@/lib/server-api";
import styles from "./customers.module.css";

type SearchParams = Promise<{
  query?: string | string[];
  status?: string | string[];
  page?: string | string[];
}>;

const PAGE_SIZE = 20;
const MAX_OFFSET = 10_000;
const MAX_PAGE = Math.floor(MAX_OFFSET / PAGE_SIZE) + 1;
const MAX_ACCESSIBLE_RECORDS = MAX_OFFSET + PAGE_SIZE;
const statusFilters = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Inactive", value: "inactive" },
] as const;

type CustomerStatus = (typeof statusFilters)[number]["value"];

function compactNumber(value: number) {
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function activityDate(value: string | null) {
  if (!value) return "No activity yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: date.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  }).format(date);
}

function pageHref(query: string, status: CustomerStatus, page: number) {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (status !== "all") params.set("status", status);
  if (page > 1) params.set("page", String(page));
  const suffix = params.toString();
  return suffix ? `/customers?${suffix}` : "/customers";
}

export default async function CustomersPage({ searchParams }: { searchParams: SearchParams }) {
  const profile = await getCurrentProfile();
  if (!profile) redirect("/sign-in");
  if (profile.role !== "admin") redirect("/dashboard");

  const params = await searchParams;
  if (
    Array.isArray(params.query) ||
    Array.isArray(params.status) ||
    Array.isArray(params.page)
  ) {
    redirect("/customers");
  }
  const query = params.query?.trim().slice(0, 160) ?? "";
  const status: CustomerStatus = statusFilters.some((filter) => filter.value === params.status)
    ? (params.status as CustomerStatus)
    : "all";
  const rawPage = params.page ?? "1";
  if (!/^(0|[1-9]\d*)$/.test(rawPage)) redirect(pageHref(query, status, 1));
  const requestedPage = Number(rawPage);
  if (requestedPage === 0) redirect(pageHref(query, status, 1));
  if (!Number.isSafeInteger(requestedPage)) redirect(pageHref(query, status, MAX_PAGE));
  const validPage = requestedPage;
  if (validPage > MAX_PAGE) redirect(pageHref(query, status, MAX_PAGE));
  const page = validPage;
  const offset = (page - 1) * PAGE_SIZE;
  const data = await getCustomers({ query, status, limit: PAGE_SIZE, offset });
  if (!data) redirect("/sign-in");
  const lastAvailablePage = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  if (page > lastAvailablePage && data.total > 0 && data.items.length === 0) {
    redirect(pageHref(query, status, Math.min(lastAvailablePage, MAX_PAGE)));
  }

  const activeCount = data.items.filter((customer) => customer.is_active).length;
  const conversationCount = data.items.reduce(
    (total, customer) => total + customer.conversation_count,
    0,
  );
  const resolvedCount = data.items.reduce(
    (total, customer) => total + customer.resolved_conversation_count,
    0,
  );
  const resolvedRate = conversationCount
    ? `${Math.round((resolvedCount / conversationCount) * 100)}%`
    : "—";
  const resultStart = data.total ? offset + 1 : 0;
  const resultEnd = Math.min(offset + data.items.length, data.total);
  const hasPrevious = page > 1;
  const hasNext = page < MAX_PAGE && offset + data.items.length < data.total;

  const metrics = [
    { label: "Customer records", value: compactNumber(data.total), note: status === "all" ? "Tenant directory" : `${status} filter` },
    { label: "Active in view", value: String(activeCount), note: `${data.items.length} shown` },
    { label: "Conversations in view", value: compactNumber(conversationCount), note: "Current page" },
    { label: "Resolution in view", value: resolvedRate, note: "Current page" },
  ];

  return (
    <div className={styles.workspace}>
      <header className={styles.pageHeader}>
        <div>
          <p className="eyebrow">Workspace directory</p>
          <h1 className={`${styles.pageTitle} display-type`}>Customers</h1>
          <p className={styles.pageIntro}>
            Manage the verified customer context used to personalise every voice conversation.
          </p>
        </div>
        <div className={styles.directoryHeaderActions}>
          <div className={styles.scopeNote}>
            <ShieldCheck size={17} strokeWidth={1.7} aria-hidden="true" />
            <span><strong>Tenant isolated</strong>Only {profile.workspace_name} records</span>
          </div>
          <Link href="/customers/new" className="button button-primary">
            <UserPlus size={16} aria-hidden="true" /> Add customer
          </Link>
        </div>
      </header>

      <dl className={styles.metrics} aria-label="Customer directory metrics">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
            <span>{metric.note}</span>
          </div>
        ))}
      </dl>

      <section className={styles.directory} aria-labelledby="directory-title">
        <div className={styles.directoryHeading}>
          <div>
            <p className="eyebrow">Customer profiles</p>
            <h2 id="directory-title">Directory</h2>
          </div>
          <span>{data.total} {data.total === 1 ? "record" : "records"}</span>
        </div>

        <div className={styles.toolbar}>
          <form className={styles.searchForm} action="/customers" method="get" role="search">
            <Search size={17} strokeWidth={1.8} aria-hidden="true" />
            <label className="sr-only" htmlFor="customer-search">Search customers</label>
            <input
              id="customer-search"
              name="query"
              type="search"
              autoComplete="off"
              defaultValue={query}
              placeholder="Search name or reference…"
            />
            {status !== "all" && <input type="hidden" name="status" value={status} />}
            <button type="submit">Search</button>
          </form>

          <nav className={styles.filters} aria-label="Filter customers by profile status">
            {statusFilters.map((filter) => (
              <Link
                key={filter.value}
                href={pageHref(query, filter.value, 1)}
                className={`${styles.filter} ${status === filter.value ? styles.filterActive : ""}`}
                aria-current={status === filter.value ? "page" : undefined}
              >
                {filter.label}
              </Link>
            ))}
          </nav>
        </div>

        {data.items.length ? (
          <>
            <div className={styles.tableWrap}>
              <table className={styles.customerTable}>
                <caption className="sr-only">Customers in {profile.workspace_name}</caption>
                <thead>
                  <tr>
                    <th scope="col">Customer</th>
                    <th scope="col">Status</th>
                    <th scope="col">Agent profile</th>
                    <th scope="col">Conversations</th>
                    <th scope="col">Last activity</th>
                    <th scope="col"><span className="sr-only">Open customer</span></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((customer) => {
                    const customerResolvedRate = customer.conversation_count
                      ? Math.round(
                          (customer.resolved_conversation_count / customer.conversation_count) * 100,
                        )
                      : null;
                    return (
                      <tr key={customer.id}>
                        <td data-label="Customer">
                          <Link href={`/customers/${customer.id}`} className={styles.customerIdentity}>
                            <span className={styles.avatar} aria-hidden="true">{customer.initials}</span>
                            <span>
                              <strong>{customer.full_name}</strong>
                              <small>{customer.external_ref}</small>
                            </span>
                          </Link>
                        </td>
                        <td data-label="Status">
                          <span className={`${styles.status} ${customer.is_active ? styles.active : styles.inactive}`}>
                            <span aria-hidden="true" />
                            {customer.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td data-label="Agent profile">
                          <span className={styles.stackValue}>
                            <strong>{customer.preferred_language}</strong>
                            <small>{customer.plan_name} plan</small>
                          </span>
                        </td>
                        <td data-label="Conversations">
                          <span className={styles.conversationValue}>
                            <strong>{customer.conversation_count}</strong>
                            <small>
                              {customerResolvedRate === null ? "No outcomes" : `${customerResolvedRate}% resolved`}
                            </small>
                          </span>
                        </td>
                        <td data-label="Last activity">
                          <time className={styles.activityValue} dateTime={customer.last_conversation_at ?? undefined}>
                            {activityDate(customer.last_conversation_at)}
                          </time>
                        </td>
                        <td className={styles.openCell}>
                          <Link
                            href={`/customers/${customer.id}`}
                            className={styles.openButton}
                            aria-label={`Open ${customer.full_name}`}
                          >
                            <ArrowRight size={16} strokeWidth={1.8} aria-hidden="true" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <footer className={styles.pagination} aria-label="Customer directory pagination">
              <p>
                Showing {resultStart}–{resultEnd} of {data.total}
                {data.total > MAX_ACCESSIBLE_RECORDS
                  ? ` · Refine filters to reach records beyond the first ${MAX_ACCESSIBLE_RECORDS.toLocaleString("en-IN")}`
                  : ""}
              </p>
              <div>
                {hasPrevious ? (
                  <Link href={pageHref(query, status, page - 1)} rel="prev">
                    <ArrowLeft size={15} aria-hidden="true" /> Previous
                  </Link>
                ) : (
                  <span aria-disabled="true"><ArrowLeft size={15} aria-hidden="true" /> Previous</span>
                )}
                <small>Page {page}</small>
                {hasNext ? (
                  <Link href={pageHref(query, status, page + 1)} rel="next">
                    Next <ArrowRight size={15} aria-hidden="true" />
                  </Link>
                ) : (
                  <span aria-disabled="true">Next <ArrowRight size={15} aria-hidden="true" /></span>
                )}
              </div>
            </footer>
          </>
        ) : (
          <div className={styles.emptyState}>
            <span aria-hidden="true">
              {query || status !== "all" ? <Search size={21} aria-hidden="true" /> : <UsersRound size={21} aria-hidden="true" />}
            </span>
            <h3>{query || status !== "all" ? "No matching customers" : "Your directory is ready"}</h3>
            <p>
              {query || status !== "all"
                ? "Try a different name or reference, or return to the complete directory."
                : "Customer records will appear here once they have been added to this workspace."}
            </p>
            {(query || status !== "all") && (
              <Link href="/customers" className="button button-quiet">Clear filters</Link>
            )}
          </div>
        )}
      </section>

      <footer className={styles.directoryFootnote}>
        <CheckCircle2 size={15} strokeWidth={1.8} aria-hidden="true" />
        <span>Saved changes are used the next time customer context is loaded.</span>
        <span aria-hidden="true">·</span>
        <UserRoundCheck size={15} strokeWidth={1.8} aria-hidden="true" />
        <span>Customer identity is verified by your backend.</span>
      </footer>
    </div>
  );
}

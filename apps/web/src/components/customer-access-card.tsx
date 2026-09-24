"use client";

import { CheckCircle2, KeyRound, LoaderCircle, Mail, RotateCw, ShieldOff } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { CustomerAccess, CustomerDetail } from "@/lib/api-types";
import { parseCustomerDetail } from "@/lib/api-validation";
import styles from "./customer-access-card.module.css";

const statusCopy: Record<CustomerAccess["status"], { label: string; detail: string }> = {
  not_invited: {
    label: "Not invited",
    detail: "No account invitation has been sent yet.",
  },
  queued: {
    label: "Invitation queued",
    detail: "Delivery is queued safely and will retry automatically if Clerk is unavailable.",
  },
  pending: {
    label: "Invitation pending",
    detail: "The customer can use the emailed link to create their Clerk account.",
  },
  accepted: {
    label: "Access active",
    detail: "Clerk identity is linked to this tenant-scoped customer record.",
  },
  revoked: {
    label: "Access revoked",
    detail: "This account cannot enter the customer workspace.",
  },
  expired: {
    label: "Invitation expired",
    detail: "Send a fresh invitation to restore the sign-up path.",
  },
  failed: {
    label: "Invitation not sent",
    detail: "The profile is safe, but Clerk did not confirm the invitation.",
  },
};

function formatDate(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

async function errorDetail(response: Response) {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) return body.detail;
  } catch {
    // Use the stable fallback below.
  }
  return "Customer access could not be updated.";
}

export function CustomerAccessCard({ customer }: { customer: CustomerDetail }) {
  const router = useRouter();
  const [access, setAccess] = useState(customer.access);
  const [busy, setBusy] = useState<"invitation" | "revoke" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!access) {
    return (
      <section className={styles.card} id="customer-access" aria-labelledby="customer-access-title">
        <p className="eyebrow">Workspace access</p>
        <h2 id="customer-access-title">No access account</h2>
        <p className={styles.description}>This legacy profile has no customer login attached.</p>
      </section>
    );
  }

  const copy = statusCopy[access.status];
  const isLinked = access.accepted_at !== null;
  const inviteLabel = isLinked
    ? "Restore access"
    : access.status === "pending"
      ? "Resend invitation"
      : "Send invitation";

  async function mutate(action: "invitation" | "revoke") {
    if (busy) return;
    setBusy(action);
    setError(null);
    try {
      const response = await fetch(
        `/api/customers/${encodeURIComponent(customer.id)}/access/${action}`,
        { method: "POST" },
      );
      if (!response.ok) {
        setError(await errorDetail(response));
        return;
      }
      const updated = parseCustomerDetail(await response.json());
      if (!updated?.access) {
        setError("The access update could not be verified.");
        return;
      }
      setAccess(updated.access);
      router.refresh();
    } catch {
      setError("The application service is unavailable. Please try again.");
    } finally {
      setBusy(null);
    }
  }

  const invitedAt = formatDate(access.invited_at);
  const expiresAt = formatDate(access.expires_at);

  return (
    <section className={styles.card} id="customer-access" aria-labelledby="customer-access-title">
      <div className={styles.heading}>
        <div>
          <p className="eyebrow">Workspace access</p>
          <h2 id="customer-access-title">Customer sign-in</h2>
        </div>
        <KeyRound size={18} aria-hidden="true" />
      </div>

      <div className={`${styles.status} ${styles[access.status]}`}>
        <span aria-hidden="true">
          {access.status === "accepted" ? <CheckCircle2 size={16} /> : <Mail size={16} />}
        </span>
        <div>
          <strong>{copy.label}</strong>
          <p>{copy.detail}</p>
        </div>
      </div>

      <dl className={styles.details}>
        <div><dt>Email</dt><dd title={access.email}>{access.email}</dd></div>
        {invitedAt && <div><dt>Last invited</dt><dd>{invitedAt}</dd></div>}
        {access.status === "pending" && expiresAt && (
          <div><dt>Link expires</dt><dd>{expiresAt}</dd></div>
        )}
      </dl>

      {error && <p className={styles.error} role="alert">{error}</p>}

      <div className={styles.actions}>
        {access.status !== "accepted" && access.status !== "queued" && (
          <button type="button" onClick={() => mutate("invitation")} disabled={busy !== null}>
            {busy === "invitation" ? <LoaderCircle className={styles.spinner} size={15} /> : <RotateCw size={15} />}
            {busy === "invitation" ? "Updating" : inviteLabel}
          </button>
        )}
        {access.is_active && (
          <button className={styles.revokeButton} type="button" onClick={() => mutate("revoke")} disabled={busy !== null}>
            {busy === "revoke" ? <LoaderCircle className={styles.spinner} size={15} /> : <ShieldOff size={15} />}
            {busy === "revoke" ? "Revoking" : "Revoke access"}
          </button>
        )}
      </div>
    </section>
  );
}

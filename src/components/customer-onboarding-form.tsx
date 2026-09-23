"use client";

import { ArrowRight, LoaderCircle, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { parseCustomerDetail } from "@/lib/api-validation";
import styles from "./customer-onboarding.module.css";

const languages = ["English", "Hindi", "Marathi", "Tamil", "Telugu", "Kannada"];
const plans = ["Essential", "Growth", "Premium"];

async function errorDetail(response: Response) {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Use the stable fallback below for non-JSON failures.
  }
  return "The customer could not be created. Please try again.";
}

export function CustomerOnboardingForm() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    const externalRef = String(form.get("external_ref") ?? "").trim();
    const payload = {
      full_name: String(form.get("full_name") ?? ""),
      email: String(form.get("email") ?? ""),
      ...(externalRef ? { external_ref: externalRef } : {}),
      preferred_language: String(form.get("preferred_language") ?? "English"),
      plan_name: String(form.get("plan_name") ?? "Essential"),
    };

    try {
      const response = await fetch("/api/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setError(await errorDetail(response));
        return;
      }
      const customer = parseCustomerDetail(await response.json());
      if (!customer) {
        setError("The customer was created, but the response could not be verified.");
        return;
      }
      router.push(`/customers/${encodeURIComponent(customer.id)}`);
      router.refresh();
    } catch {
      setError("The application service is unavailable. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <div className={styles.formHeading}>
        <div>
          <p className="eyebrow">Customer identity</p>
          <h2>Profile and access</h2>
        </div>
        <span><ShieldCheck size={16} aria-hidden="true" /> Tenant scoped</span>
      </div>

      <div className={styles.fields}>
        <label className={styles.fullField}>
          <span>Full name</span>
          <input name="full_name" type="text" autoComplete="name" maxLength={160} required />
          <small>Used in the workspace and the customer&apos;s voice context.</small>
        </label>

        <label className={styles.fullField}>
          <span>Email address</span>
          <input name="email" type="email" autoComplete="email" maxLength={254} required />
          <small>Clerk sends the secure account invitation to this address.</small>
        </label>

        <label>
          <span>Customer reference <em>Optional</em></span>
          <input name="external_ref" type="text" maxLength={120} placeholder="Auto-generated if empty" />
        </label>

        <label>
          <span>Preferred language</span>
          <select name="preferred_language" defaultValue="English">
            {languages.map((language) => <option key={language}>{language}</option>)}
          </select>
        </label>

        <label className={styles.fullField}>
          <span>Plan</span>
          <select name="plan_name" defaultValue="Essential">
            {plans.map((plan) => <option key={plan}>{plan}</option>)}
          </select>
        </label>
      </div>

      {error && <p className={styles.error} role="alert">{error}</p>}

      <footer className={styles.formFooter}>
        <p>
          Creating this customer also prepares their default voice agent and attempts to send
          one invitation. You can retry safely from the customer profile.
        </p>
        <button className="button button-primary" type="submit" disabled={submitting}>
          {submitting ? (
            <><LoaderCircle className={styles.spinner} size={16} aria-hidden="true" /> Creating</>
          ) : (
            <>Create and invite <ArrowRight size={16} aria-hidden="true" /></>
          )}
        </button>
      </footer>
    </form>
  );
}

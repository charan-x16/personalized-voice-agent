"use client";

import { Check, LoaderCircle, RefreshCcw, Save, ShieldCheck, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition, type FormEvent } from "react";

import type { CustomerDetail, CustomerUpdateRequest } from "@/lib/api-types";
import { parseCustomerDetail } from "@/lib/api-validation";
import { useEditorDraftState, useUnsavedEditor } from "@/components/editor-drafts";
import styles from "./customer-editor.module.css";

const PROFILE_CONFLICT_DETAIL =
  "Customer profile was updated by another administrator. Refresh and try again.";

const languageOptions = [
  "English",
  "Hindi",
  "Bengali",
  "Gujarati",
  "Kannada",
  "Malayalam",
  "Marathi",
  "Punjabi",
  "Tamil",
  "Telugu",
];

type Feedback =
  | { tone: "success"; message: string }
  | { tone: "error"; message: string }
  | { tone: "neutral"; message: string }
  | { tone: "conflict"; message: string }
  | null;

type FieldErrors = {
  fullName?: string;
  language?: string;
  planName?: string;
};

async function responseDetail(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof payload.detail === "string"
    ) {
      return payload.detail;
    }
  } catch {
    // Use the stable fallback when the response has no readable JSON body.
  }
  return "The customer profile could not be updated.";
}

async function parsedCustomerDetail(response: Response): Promise<CustomerDetail | null> {
  try {
    return parseCustomerDetail(await response.json());
  } catch {
    return null;
  }
}

export function CustomerEditor({ customer }: { customer: CustomerDetail }) {
  const router = useRouter();
  const draftKey = `${customer.id}:profile:${customer.profile_revision}`;
  const [savedCustomer, setSavedCustomer] = useState(customer);
  const [fullName, setFullName] = useEditorDraftState(`${draftKey}:fullName`, customer.full_name);
  const [language, setLanguage] = useEditorDraftState(`${draftKey}:language`, customer.preferred_language);
  const [planName, setPlanName] = useEditorDraftState(`${draftKey}:planName`, customer.plan_name);
  const [isActive, setIsActive] = useEditorDraftState(`${draftKey}:isActive`, customer.is_active);
  const [isPending, setIsPending] = useState(false);
  const [isRefreshing, startRefresh] = useTransition();
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const fullNameRef = useRef<HTMLInputElement>(null);
  const languageRef = useRef<HTMLSelectElement>(null);
  const planNameRef = useRef<HTMLInputElement>(null);
  const reloadButtonRef = useRef<HTMLButtonElement>(null);
  const isDirty =
    fullName.trim() !== savedCustomer.full_name ||
    language.trim() !== savedCustomer.preferred_language ||
    planName.trim() !== savedCustomer.plan_name ||
    isActive !== savedCustomer.is_active;
  const hasConflict = feedback?.tone === "conflict";
  const isBusy = isPending || isRefreshing;
  const isLocked = isBusy || hasConflict;

  const clearDraft = useUnsavedEditor(isDirty, draftKey);

  useEffect(() => {
    if (hasConflict) reloadButtonRef.current?.focus();
  }, [hasConflict]);

  function clearFeedback() {
    setFeedback((current) => (current?.tone === "conflict" ? current : null));
  }

  function clearFieldError(field: keyof FieldErrors) {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      return { ...current, [field]: undefined };
    });
  }

  function resetForm() {
    if (hasConflict) return;
    setFullName(savedCustomer.full_name);
    setLanguage(savedCustomer.preferred_language);
    setPlanName(savedCustomer.plan_name);
    setIsActive(savedCustomer.is_active);
    setFieldErrors({});
    setFeedback(null);
  }

  async function saveCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isBusy || hasConflict) return;

    const nextFullName = fullName.trim();
    const nextLanguage = language.trim();
    const nextPlanName = planName.trim();
    const nextFieldErrors: FieldErrors = {};
    if (!nextFullName) nextFieldErrors.fullName = "Enter the customer's full name.";
    if (!nextLanguage) nextFieldErrors.language = "Choose a preferred language.";
    if (!nextPlanName) nextFieldErrors.planName = "Enter the customer's plan name.";

    if (Object.keys(nextFieldErrors).length) {
      setFieldErrors(nextFieldErrors);
      setFeedback({ tone: "error", message: "Review the highlighted profile fields." });
      requestAnimationFrame(() => {
        if (nextFieldErrors.fullName) fullNameRef.current?.focus();
        else if (nextFieldErrors.language) languageRef.current?.focus();
        else planNameRef.current?.focus();
      });
      return;
    }
    setFieldErrors({});

    const update: CustomerUpdateRequest = {
      expected_revision: savedCustomer.profile_revision,
    };
    if (nextFullName !== savedCustomer.full_name) update.full_name = nextFullName;
    if (nextLanguage !== savedCustomer.preferred_language) update.preferred_language = nextLanguage;
    if (nextPlanName !== savedCustomer.plan_name) update.plan_name = nextPlanName;
    if (isActive !== savedCustomer.is_active) update.is_active = isActive;
    if (!isDirty || Object.keys(update).length === 1) {
      setFeedback({ tone: "neutral", message: "No changes to save." });
      return;
    }

    setIsPending(true);
    setFeedback(null);

    try {
      const response = await fetch(`/api/customers/${encodeURIComponent(customer.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });

      if (response.status === 409) {
        const detail = await responseDetail(response);
        if (detail !== PROFILE_CONFLICT_DETAIL) throw new Error(detail);
        setFeedback({
          tone: "conflict",
          message: "Someone updated this profile while you were editing. Reloading will replace this draft with the latest version.",
        });
        return;
      }
      if (!response.ok) throw new Error(await responseDetail(response));

      const updatedCustomer = await parsedCustomerDetail(response);
      if (
        !updatedCustomer ||
        updatedCustomer.id !== savedCustomer.id ||
        updatedCustomer.profile_revision !== savedCustomer.profile_revision + 1 ||
        updatedCustomer.full_name !== nextFullName ||
        updatedCustomer.preferred_language !== nextLanguage ||
        updatedCustomer.plan_name !== nextPlanName ||
        updatedCustomer.is_active !== isActive
      ) {
        setFeedback({
          tone: "conflict",
          message:
            "The saved response could not be verified. Reload the latest profile before editing again.",
        });
        return;
      }

      setSavedCustomer(updatedCustomer);
      clearDraft();
      setFullName(updatedCustomer.full_name);
      setLanguage(updatedCustomer.preferred_language);
      setPlanName(updatedCustomer.plan_name);
      setIsActive(updatedCustomer.is_active);
      setFeedback({ tone: "success", message: "Customer profile saved." });
      startRefresh(() => router.refresh());
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof Error ? error.message : "The customer profile could not be updated.",
      });
    } finally {
      setIsPending(false);
    }
  }

  const languageChoices = languageOptions.includes(language)
    ? languageOptions
    : [language, ...languageOptions];

  return (
    <section className={styles.panel} aria-labelledby="customer-settings-title">
      <div className={styles.heading}>
        <div>
          <p className="eyebrow">Agent context</p>
          <h2 id="customer-settings-title">Customer settings</h2>
        </div>
        <span className={styles.secureMark} title="Tenant-scoped update">
          <ShieldCheck size={16} strokeWidth={1.8} aria-hidden="true" />
          Scoped
        </span>
      </div>

      <form className={styles.form} onSubmit={saveCustomer} aria-busy={isBusy} noValidate>
        <div className={styles.field}>
          <label htmlFor="customer-full-name">Full name</label>
          <input
            ref={fullNameRef}
            id="customer-full-name"
            name="full_name"
            type="text"
            value={fullName}
            minLength={1}
            maxLength={160}
            autoComplete="off"
            required
            disabled={isLocked}
            aria-invalid={Boolean(fieldErrors.fullName)}
            aria-describedby={fieldErrors.fullName ? "customer-full-name-error" : undefined}
            onChange={(event) => {
              setFullName(event.target.value);
              clearFieldError("fullName");
              clearFeedback();
            }}
          />
          {fieldErrors.fullName && (
            <small id="customer-full-name-error" className={styles.fieldError}>
              {fieldErrors.fullName}
            </small>
          )}
        </div>

        <div className={styles.fieldGrid}>
          <div className={styles.field}>
            <label htmlFor="customer-language">Preferred language</label>
            <select
              ref={languageRef}
              id="customer-language"
              name="preferred_language"
              value={language}
              required
              disabled={isLocked}
              aria-invalid={Boolean(fieldErrors.language)}
              aria-describedby={fieldErrors.language ? "customer-language-error" : undefined}
              onChange={(event) => {
                setLanguage(event.target.value);
                clearFieldError("language");
                clearFeedback();
              }}
            >
              {languageChoices.map((option) => (
                <option value={option} key={option}>{option}</option>
              ))}
            </select>
            {fieldErrors.language && (
              <small id="customer-language-error" className={styles.fieldError}>
                {fieldErrors.language}
              </small>
            )}
          </div>

          <div className={styles.field}>
            <label htmlFor="customer-plan">Plan name</label>
            <input
              ref={planNameRef}
              id="customer-plan"
              name="plan_name"
              type="text"
              value={planName}
              minLength={1}
              maxLength={80}
              autoComplete="off"
              required
              disabled={isLocked}
              aria-invalid={Boolean(fieldErrors.planName)}
              aria-describedby={fieldErrors.planName ? "customer-plan-error" : undefined}
              onChange={(event) => {
                setPlanName(event.target.value);
                clearFieldError("planName");
                clearFeedback();
              }}
            />
            {fieldErrors.planName && (
              <small id="customer-plan-error" className={styles.fieldError}>
                {fieldErrors.planName}
              </small>
            )}
          </div>
        </div>

        <label className={styles.accessControl} htmlFor="customer-active">
          <span>
            <strong>Customer profile status</strong>
            <small>
              {isActive
                ? "Eligible for authenticated voice access when linked to a user."
                : "Linked sign-in and voice access are blocked."}
            </small>
          </span>
          <span className={styles.switch}>
            <input
              id="customer-active"
              name="is_active"
              type="checkbox"
              checked={isActive}
              disabled={isLocked}
              onChange={(event) => {
                setIsActive(event.target.checked);
                clearFeedback();
              }}
            />
            <span aria-hidden="true" />
          </span>
        </label>

        {feedback?.tone === "conflict" && (
          <div className={styles.conflictNotice} role="alert">
            <TriangleAlert size={18} strokeWidth={1.8} aria-hidden="true" />
            <div>
              <strong>Reload required</strong>
              <p>{feedback.message}</p>
            </div>
            <button
              ref={reloadButtonRef}
              type="button"
              disabled={isRefreshing}
              onClick={() => { clearDraft(); startRefresh(() => router.refresh()); }}
            >
              <RefreshCcw
                className={isRefreshing ? styles.spinner : undefined}
                size={14}
                strokeWidth={1.9}
                aria-hidden="true"
              />
              {isRefreshing ? "Reloading…" : "Reload latest"}
            </button>
          </div>
        )}

        <div className={styles.formFooter}>
          <div className={styles.feedback} aria-live="polite" aria-atomic="true">
            {feedback?.tone === "success" && <Check size={14} strokeWidth={2.3} aria-hidden="true" />}
            {feedback && feedback.tone !== "conflict" && (
              <span
                className={
                  feedback.tone === "error"
                    ? styles.error
                    : feedback.tone === "success"
                      ? styles.success
                      : styles.neutral
                }
              >
                {feedback.message}
              </span>
            )}
          </div>
          <div className={styles.actions}>
            <button type="button" className={styles.resetButton} onClick={resetForm} disabled={isLocked}>
              Reset
            </button>
            <button type="submit" className={styles.saveButton} disabled={isLocked}>
              {isPending ? (
                <LoaderCircle className={styles.spinner} size={15} aria-hidden="true" />
              ) : (
                <Save size={15} strokeWidth={1.9} aria-hidden="true" />
              )}
              {isPending ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}

"use client";

import {
  Bot,
  Check,
  LoaderCircle,
  MessageCircleMore,
  RefreshCcw,
  Save,
  TriangleAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition, type FormEvent } from "react";

import type {
  AgentConfiguration,
  AgentConfigurationUpdateRequest,
  AgentTone,
  CustomerDetail,
} from "@/lib/api-types";
import { parseCustomerDetail, renderAgentOpeningTemplate } from "@/lib/api-validation";
import { useEditorDraftState, useUnsavedEditor } from "@/components/editor-drafts";
import styles from "./agent-configuration-editor.module.css";

const AGENT_CONFLICT_DETAIL =
  "Agent configuration was updated by another administrator. Refresh and try again.";

const tones: Array<{ value: AgentTone; label: string; description: string }> = [
  { value: "warm", label: "Warm", description: "Empathetic and conversational" },
  { value: "professional", label: "Professional", description: "Clear and composed" },
  { value: "concise", label: "Concise", description: "Direct and efficient" },
];

type Feedback =
  | { tone: "success" | "error" | "neutral" | "conflict"; message: string }
  | null;

type FieldErrors = {
  displayName?: string;
  openingMessage?: string;
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
    // Keep the stable fallback for empty or non-JSON responses.
  }
  return "The agent configuration could not be updated.";
}

async function parsedCustomerDetail(response: Response): Promise<CustomerDetail | null> {
  try {
    return parseCustomerDetail(await response.json());
  } catch {
    return null;
  }
}

export function AgentConfigurationEditor({
  customerId,
  customerFirstName,
  configuration,
}: {
  customerId: string;
  customerFirstName: string;
  configuration: AgentConfiguration;
}) {
  const router = useRouter();
  const draftKey = `${customerId}:agent:${configuration.revision}`;
  const [savedConfiguration, setSavedConfiguration] = useState(configuration);
  const [displayName, setDisplayName] = useEditorDraftState(`${draftKey}:displayName`, configuration.display_name);
  const [openingMessage, setOpeningMessage] = useEditorDraftState(`${draftKey}:openingMessage`, configuration.opening_message);
  const [tone, setTone] = useEditorDraftState<AgentTone>(`${draftKey}:tone`, configuration.tone);
  const [instructions, setInstructions] = useEditorDraftState(`${draftKey}:instructions`, configuration.instructions);
  const [isPending, setIsPending] = useState(false);
  const [isRefreshing, startRefresh] = useTransition();
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const displayNameRef = useRef<HTMLInputElement>(null);
  const openingMessageRef = useRef<HTMLTextAreaElement>(null);
  const reloadButtonRef = useRef<HTMLButtonElement>(null);

  const isDirty =
    displayName.trim() !== savedConfiguration.display_name ||
    openingMessage.trim() !== savedConfiguration.opening_message ||
    tone !== savedConfiguration.tone ||
    instructions.trim() !== savedConfiguration.instructions;
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
    setDisplayName(savedConfiguration.display_name);
    setOpeningMessage(savedConfiguration.opening_message);
    setTone(savedConfiguration.tone);
    setInstructions(savedConfiguration.instructions);
    setFieldErrors({});
    setFeedback(null);
  }

  function reloadLatest() {
    clearDraft();
    startRefresh(() => router.refresh());
  }

  async function saveConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isBusy || hasConflict) return;

    const nextDisplayName = displayName.trim();
    const nextOpeningMessage = openingMessage.trim();
    const nextInstructions = instructions.trim();
    const nextFieldErrors: FieldErrors = {};
    if (!nextDisplayName) nextFieldErrors.displayName = "Enter a name for this voice agent.";
    if (!nextOpeningMessage) {
      nextFieldErrors.openingMessage = "Enter an opening message.";
    } else if (!renderAgentOpeningTemplate(nextOpeningMessage, customerFirstName).valid) {
      nextFieldErrors.openingMessage =
        "Use {first_name} at most once, and pair literal braces as {{ or }}.";
    }

    if (Object.keys(nextFieldErrors).length) {
      setFieldErrors(nextFieldErrors);
      setFeedback({ tone: "error", message: "Review the highlighted agent fields." });
      requestAnimationFrame(() => {
        if (nextFieldErrors.displayName) displayNameRef.current?.focus();
        else openingMessageRef.current?.focus();
      });
      return;
    }
    setFieldErrors({});

    const update: AgentConfigurationUpdateRequest = {
      expected_revision: savedConfiguration.revision,
    };
    if (nextDisplayName !== savedConfiguration.display_name) update.display_name = nextDisplayName;
    if (nextOpeningMessage !== savedConfiguration.opening_message) {
      update.opening_message = nextOpeningMessage;
    }
    if (tone !== savedConfiguration.tone) update.tone = tone;
    if (nextInstructions !== savedConfiguration.instructions) update.instructions = nextInstructions;

    if (!isDirty || Object.keys(update).length === 1) {
      setFeedback({ tone: "neutral", message: "No changes to save." });
      return;
    }

    setIsPending(true);
    setFeedback(null);
    try {
      const response = await fetch(
        `/api/customers/${encodeURIComponent(customerId)}/agent-configuration`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(update),
        },
      );

      if (response.status === 409) {
        const detail = await responseDetail(response);
        if (detail !== AGENT_CONFLICT_DETAIL) throw new Error(detail);
        setFeedback({
          tone: "conflict",
          message: "Someone updated this agent while you were editing. Reloading will replace this draft with the latest version.",
        });
        return;
      }
      if (!response.ok) throw new Error(await responseDetail(response));

      const updatedCustomer = await parsedCustomerDetail(response);
      const updatedConfiguration = updatedCustomer?.agent_configuration;
      if (
        !updatedCustomer ||
        updatedCustomer.id !== customerId ||
        !updatedConfiguration ||
        updatedConfiguration.revision !== savedConfiguration.revision + 1 ||
        updatedConfiguration.display_name !== nextDisplayName ||
        updatedConfiguration.opening_message !== nextOpeningMessage ||
        updatedConfiguration.tone !== tone ||
        updatedConfiguration.instructions !== nextInstructions
      ) {
        setFeedback({
          tone: "conflict",
          message:
            "The saved response could not be verified. Reload the latest configuration before editing again.",
        });
        return;
      }

      setSavedConfiguration(updatedConfiguration);
      clearDraft();
      setDisplayName(updatedConfiguration.display_name);
      setOpeningMessage(updatedConfiguration.opening_message);
      setTone(updatedConfiguration.tone);
      setInstructions(updatedConfiguration.instructions);
      setFeedback({ tone: "success", message: "Agent configuration saved." });
      startRefresh(() => router.refresh());
    } catch (error) {
      setFeedback({
        tone: "error",
        message: error instanceof Error ? error.message : "The agent configuration could not be updated.",
      });
    } finally {
      setIsPending(false);
    }
  }

  const parsedOpeningPreview = renderAgentOpeningTemplate(
    openingMessage.trim(),
    customerFirstName,
  );
  const openingPreview = openingMessage.trim()
    ? parsedOpeningPreview.valid
      ? parsedOpeningPreview.rendered
      : "Fix the greeting syntax to see a preview."
    : "Your opening message will appear here.";

  return (
    <section className={styles.panel} aria-labelledby="agent-configuration-title">
      <div className={styles.heading}>
        <div className={styles.headingIcon} aria-hidden="true">
          <Bot size={20} strokeWidth={1.65} aria-hidden="true" />
        </div>
        <div>
          <p className="eyebrow">Conversation design</p>
          <h2 id="agent-configuration-title">Voice agent</h2>
        </div>
        <span className={styles.revision}>Revision {savedConfiguration.revision}</span>
      </div>

      <form className={styles.form} onSubmit={saveConfiguration} aria-busy={isBusy} noValidate>
        <div className={styles.primaryColumn}>
          <div className={styles.field}>
            <label htmlFor="agent-display-name">Agent name</label>
            <input
              ref={displayNameRef}
              id="agent-display-name"
              name="display_name"
              type="text"
              value={displayName}
              minLength={1}
              maxLength={80}
              autoComplete="off"
              required
              disabled={isLocked}
              aria-invalid={Boolean(fieldErrors.displayName)}
              aria-describedby={
                fieldErrors.displayName
                  ? "agent-display-name-count agent-display-name-error"
                  : "agent-display-name-count"
              }
              onChange={(event) => {
                setDisplayName(event.target.value);
                clearFieldError("displayName");
                clearFeedback();
              }}
            />
            <small id="agent-display-name-count">{displayName.length}/80 characters</small>
            {fieldErrors.displayName && (
              <small id="agent-display-name-error" className={styles.fieldError}>
                {fieldErrors.displayName}
              </small>
            )}
          </div>

          <fieldset className={styles.toneFieldset}>
            <legend>Conversation tone</legend>
            <div className={styles.toneOptions}>
              {tones.map((option) => (
                <label
                  className={`${styles.toneOption} ${tone === option.value ? styles.toneOptionSelected : ""}`}
                  key={option.value}
                >
                  <input
                    type="radio"
                    name="tone"
                    value={option.value}
                    checked={tone === option.value}
                    disabled={isLocked}
                    onChange={() => {
                      setTone(option.value);
                      clearFeedback();
                    }}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.description}</small>
                  </span>
                  <span className={styles.radioMark} aria-hidden="true">
                    {tone === option.value && <Check size={11} strokeWidth={2.5} aria-hidden="true" />}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className={styles.preview}>
            <span>
              <MessageCircleMore size={14} strokeWidth={1.8} aria-hidden="true" />
              {parsedOpeningPreview.usedFallback ? "Runtime fallback preview" : "Opening preview"}
            </span>
            <p>{openingPreview}</p>
            {parsedOpeningPreview.usedFallback && (
              <small className={styles.previewWarning} role="status">
                The personalised greeting exceeds the 500-character runtime limit, so calls use
                this safe fallback. Shorten the template to use the customer name.
              </small>
            )}
          </div>
        </div>

        <div className={styles.promptColumn}>
          <div className={styles.field}>
            <div className={styles.labelRow}>
              <label htmlFor="agent-opening-message">Opening message</label>
              <span id="agent-opening-message-count">{openingMessage.length}/500</span>
            </div>
            <textarea
              ref={openingMessageRef}
              id="agent-opening-message"
              name="opening_message"
              value={openingMessage}
              minLength={1}
              maxLength={500}
              rows={4}
              required
              disabled={isLocked}
              aria-invalid={Boolean(fieldErrors.openingMessage)}
              aria-describedby={
                fieldErrors.openingMessage
                  ? "agent-opening-message-count opening-message-help agent-opening-message-error"
                  : "agent-opening-message-count opening-message-help"
              }
              onChange={(event) => {
                setOpeningMessage(event.target.value);
                clearFieldError("openingMessage");
                clearFeedback();
              }}
            />
            <small id="opening-message-help">
              Use <code translate="no">{"{first_name}"}</code> at most once to personalise; write literal braces as <code translate="no">{"{{"}</code> and <code translate="no">{"}}"}</code>.
            </small>
            {fieldErrors.openingMessage && (
              <small id="agent-opening-message-error" className={styles.fieldError}>
                {fieldErrors.openingMessage}
              </small>
            )}
          </div>

          <div className={styles.field}>
            <div className={styles.labelRow}>
              <label htmlFor="agent-instructions">Custom instructions</label>
              <span id="agent-instructions-count">{instructions.length}/2000</span>
            </div>
            <textarea
              id="agent-instructions"
              name="instructions"
              value={instructions}
              maxLength={2000}
              rows={7}
              disabled={isLocked}
              aria-describedby="agent-instructions-count agent-instructions-help"
              onChange={(event) => {
                setInstructions(event.target.value);
                clearFeedback();
              }}
            />
            <small id="agent-instructions-help">
              Describe behaviour here; keep personal data in verified backend tools.
            </small>
          </div>
        </div>

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
              onClick={reloadLatest}
              disabled={isRefreshing}
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
              <span className={styles[feedback.tone]}>{feedback.message}</span>
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
              {isPending ? "Saving…" : "Save agent"}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}

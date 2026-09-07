"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  LoaderCircle,
  LockKeyhole,
  UserRound,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type CSSProperties, type FormEvent } from "react";

import { Brand } from "@/components/brand";
import styles from "./sign-in.module.css";

type DemoAccountId = "customer" | "admin";

const demoAccounts = {
  customer: {
    id: "customer",
    email: "rahul@example.com",
    name: "Rahul Mehta",
    label: "Customer",
    description: "Try a personal voice room and conversation history.",
    destination: "/dashboard",
    icon: UserRound,
  },
  admin: {
    id: "admin",
    email: "ananya@acme.example",
    name: "Ananya Rao",
    label: "Workspace admin",
    description: "Manage customer profiles, language, plans, and access.",
    destination: "/customers",
    icon: UsersRound,
  },
} as const;

function SignInWave() {
  const heights = [12, 18, 26, 34, 42, 54, 46, 63, 72, 58, 76, 88, 68, 81, 96, 72, 91, 76, 64, 84, 69, 56, 61, 47, 53, 39, 31, 36, 23, 18, 12];

  return (
    <div className={styles.wave} aria-hidden="true">
      {heights.map((height, index) => (
        <span
          key={`${height}-${index}`}
          style={{ "--wave-height": `${height}%`, "--wave-index": index } as CSSProperties}
        />
      ))}
    </div>
  );
}

export default function SignInPage() {
  const router = useRouter();
  const [selectedAccount, setSelectedAccount] = useState<DemoAccountId>("customer");
  const [isPending, setIsPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleDemoSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending) return;

    setIsPending(true);
    setErrorMessage(null);
    const account = demoAccounts[selectedAccount];

    try {
      const response = await fetch("/api/auth/demo-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: account.email }),
      });

      if (!response.ok) {
        let detail = "The demo workspace could not be opened. Please try again.";
        try {
          const payload: unknown = await response.json();
          if (
            typeof payload === "object" &&
            payload !== null &&
            "detail" in payload &&
            typeof payload.detail === "string"
          ) {
            detail = payload.detail;
          }
        } catch {
          // Keep the useful fallback when the server returns no JSON body.
        }
        throw new Error(detail);
      }

      router.replace(account.destination);
      router.refresh();
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "The demo workspace could not be opened. Please try again.",
      );
      setIsPending(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.storyPanel} aria-label="About Svara">
        <div className={styles.storyHeader}>
          <Brand inverse />
          <Link href="/" className={styles.backLink}>
            Back to home
            <ArrowLeft size={15} aria-hidden="true" />
          </Link>
        </div>

        <div className={styles.storyCenter}>
          <p className={styles.eyebrow}>Your private voice workspace</p>
          <blockquote>
            &ldquo;Every customer should feel recognised before they have to explain.&rdquo;
          </blockquote>
          <SignInWave />
        </div>

        <div className={styles.storyFooter}>
          <div>
            <LockKeyhole size={15} aria-hidden="true" />
            Secure by design
          </div>
          <p>Personal voice. Real context.</p>
        </div>
      </section>

      <section className={styles.formPanel} aria-labelledby="sign-in-title">
        <div className={styles.mobileBrand}>
          <Brand />
          <Link href="/" aria-label="Back to home">
            <ArrowLeft size={18} />
          </Link>
        </div>

        <div className={styles.formWrap}>
          <div className={styles.formHeading}>
            <p className={styles.stepLabel}>Demo workspace</p>
            <h1 id="sign-in-title">Choose your view.</h1>
            <p>Explore the voice experience as a customer or manage the workspace as an administrator.</p>
          </div>

          <form className={styles.form} onSubmit={handleDemoSignIn} aria-busy={isPending}>
            <fieldset className={styles.accountPicker} aria-describedby="demo-account-note">
              <legend>Demo account</legend>
              {Object.values(demoAccounts).map((account) => {
                const Icon = account.icon;
                const checked = selectedAccount === account.id;
                return (
                  <label
                    className={`${styles.accountOption} ${checked ? styles.accountOptionSelected : ""}`}
                    key={account.id}
                  >
                    <input
                      type="radio"
                      name="demo-account"
                      value={account.id}
                      checked={checked}
                      disabled={isPending}
                      onChange={() => {
                        setSelectedAccount(account.id);
                        setErrorMessage(null);
                      }}
                    />
                    <span className={styles.accountIcon} aria-hidden="true">
                      <Icon size={18} strokeWidth={1.7} />
                    </span>
                    <span className={styles.accountCopy}>
                      <span className={styles.accountTopline}>
                        <strong>{account.name}</strong>
                        <small>{account.label}</small>
                      </span>
                      <span>{account.description}</span>
                    </span>
                    <span className={styles.accountCheck} aria-hidden="true">
                      {checked && <Check size={13} strokeWidth={2.4} />}
                    </span>
                  </label>
                );
              })}
            </fieldset>

            <div className={styles.demoNote} id="demo-account-note">
              <LockKeyhole size={16} aria-hidden="true" />
              <p>
                <strong>No password is collected.</strong>
                This account contains demonstration data only.
              </p>
            </div>

            {errorMessage && (
              <p className={styles.errorMessage} role="alert">
                {errorMessage}
              </p>
            )}

            <button className={styles.submit} type="submit" disabled={isPending}>
              {isPending ? (
                <>
                  <LoaderCircle className={styles.spinner} size={17} aria-hidden="true" />
                  Opening workspace&hellip;
                </>
              ) : (
                <>
                  Continue as {demoAccounts[selectedAccount].name.split(" ")[0]}
                  <ArrowRight size={17} aria-hidden="true" />
                </>
              )}
            </button>
          </form>

          <p className={styles.disclaimer}>
            Your session is stored in a secure, HTTP-only browser cookie and expires automatically.
          </p>
        </div>

        <p className={styles.support}>
          New to Svara? <a href="mailto:hello@svara.example">Request access</a>
        </p>
      </section>
    </main>
  );
}

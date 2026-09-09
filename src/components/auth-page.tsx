import { SignIn, SignUp } from "@clerk/nextjs";
import { ArrowLeft, LockKeyhole } from "lucide-react";
import Link from "next/link";
import type { CSSProperties } from "react";

import { Brand } from "@/components/brand";
import styles from "@/app/sign-in/sign-in.module.css";

const clerkAppearance = {
  variables: {
    colorPrimary: "#171714",
    colorText: "#171714",
    colorTextSecondary: "#625f57",
    colorBackground: "#fbfaf7",
    colorInputBackground: "#ffffff",
    colorInputText: "#171714",
    borderRadius: "0.75rem",
    fontFamily: "var(--font-sans)",
  },
  elements: {
    rootBox: styles.clerkRoot,
    cardBox: styles.clerkCardBox,
    card: styles.clerkCard,
    header: styles.clerkHeader,
    socialButtonsBlockButton: styles.clerkSocialButton,
    formButtonPrimary: styles.clerkPrimaryButton,
    footerActionLink: styles.clerkLink,
    footer: styles.clerkFooter,
  },
};

function AuthWave() {
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

export function AuthPage({ mode }: { mode: "sign-in" | "sign-up" }) {
  const signingIn = mode === "sign-in";

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
          <AuthWave />
        </div>

        <div className={styles.storyFooter}>
          <div>
            <LockKeyhole size={15} aria-hidden="true" />
            Identity protected by Clerk
          </div>
          <p>Personal voice. Real context.</p>
        </div>
      </section>

      <section className={styles.formPanel} aria-labelledby="auth-title">
        <div className={styles.mobileBrand}>
          <Brand />
          <Link href="/" aria-label="Back to home">
            <ArrowLeft size={18} />
          </Link>
        </div>

        <div className={styles.formWrap}>
          <div className={styles.formHeading}>
            <p className={styles.stepLabel}>{signingIn ? "Welcome back" : "Create your account"}</p>
            <h1 id="auth-title">{signingIn ? "Sign in to Svara." : "Start with Svara."}</h1>
            <p>
              {signingIn
                ? "Access your private voice workspace and customer context."
                : "Create a secure identity, then connect it to your Svara workspace."}
            </p>
          </div>

          {signingIn ? (
            <SignIn
              appearance={clerkAppearance}
              fallbackRedirectUrl="/dashboard"
              path="/sign-in"
              routing="path"
              signUpUrl="/sign-up"
            />
          ) : (
            <SignUp
              appearance={clerkAppearance}
              fallbackRedirectUrl="/dashboard"
              path="/sign-up"
              routing="path"
              signInUrl="/sign-in"
            />
          )}

          <p className={styles.disclaimer}>
            Authentication is handled by Clerk. Svara never stores your password.
          </p>
          <p className={styles.authSwitch}>
            {signingIn ? "New to Svara?" : "Already have an account?"}{" "}
            <Link href={signingIn ? "/sign-up" : "/sign-in"}>
              {signingIn ? "Create an account" : "Sign in"}
            </Link>
          </p>
        </div>

        <p className={styles.support}>
          Need workspace access? <a href="mailto:hello@svara.example">Contact your administrator</a>
        </p>
      </section>
    </main>
  );
}

import { SignOutButton, UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { ArrowLeft, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Brand } from "@/components/brand";
import styles from "./access-pending.module.css";

export default async function AccessPendingPage() {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Brand />
        <UserButton />
      </header>
      <section className={styles.card} aria-labelledby="access-title">
        <span className={styles.icon} aria-hidden="true"><ShieldAlert size={23} /></span>
        <p className={styles.eyebrow}>Signed in securely</p>
        <h1 id="access-title">Your workspace is not linked yet.</h1>
        <p>
          Your Clerk account is valid, but its verified email does not match one active Svara
          user. Ask your workspace administrator to add that email, then try again.
        </p>
        <div className={styles.actions}>
          <Link href="/" className={styles.secondary}>
            <ArrowLeft size={16} aria-hidden="true" />
            Back home
          </Link>
          <SignOutButton redirectUrl="/sign-in">
            <button className={styles.primary} type="button">Use another account</button>
          </SignOutButton>
        </div>
      </section>
    </main>
  );
}

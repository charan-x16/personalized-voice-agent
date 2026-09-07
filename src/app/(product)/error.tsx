"use client";

import { RefreshCcw, WifiOff } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import styles from "./status.module.css";

export default function ProductError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Workspace request failed", error);
  }, [error]);

  return (
    <div className={styles.errorPanel}>
      <span className={styles.errorIcon} aria-hidden="true"><WifiOff size={22} /></span>
      <p className="eyebrow">Connection interrupted</p>
      <h1 className="display-type">We couldn’t load your workspace.</h1>
      <p className={styles.errorCopy}>
        Check your connection and try again. If this keeps happening, contact your workspace administrator.
      </p>
      <div className={styles.errorActions}>
        <button className="button button-primary" type="button" onClick={reset}>
          <RefreshCcw size={16} /> Try again
        </button>
        <Link className="button button-quiet" href="/sign-in">Return to sign in</Link>
      </div>
    </div>
  );
}

"use client";

import { RefreshCcw, WifiOff } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import styles from "./customers.module.css";

export default function CustomersError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Customer directory request failed", error);
  }, [error]);

  return (
    <div className={styles.errorState}>
      <span aria-hidden="true"><WifiOff size={22} strokeWidth={1.7} /></span>
      <p className="eyebrow">Directory interrupted</p>
      <h1 className="display-type">Your customer data is still safe.</h1>
      <p className={styles.stateCopy}>
        We could not load this tenant-scoped view. Check the API connection, then try again.
      </p>
      <div>
        <button className="button button-primary" type="button" onClick={reset}>
          <RefreshCcw size={16} aria-hidden="true" /> Try again
        </button>
        <Link className="button button-quiet" href="/customers">Customer directory</Link>
      </div>
    </div>
  );
}

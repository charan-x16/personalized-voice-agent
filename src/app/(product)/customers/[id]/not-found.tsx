import { ArrowLeft, UserRoundX } from "lucide-react";
import Link from "next/link";

import styles from "../customers.module.css";

export default function CustomerNotFound() {
  return (
    <div className={styles.notFound}>
      <span aria-hidden="true"><UserRoundX size={22} strokeWidth={1.7} /></span>
      <p className="eyebrow">Customer unavailable</p>
      <h1 className="display-type">This profile is not in your workspace.</h1>
      <p className={styles.stateCopy}>
        The customer may have been removed, or your authenticated workspace does not have access.
      </p>
      <Link href="/customers" className="button button-primary">
        <ArrowLeft size={16} aria-hidden="true" /> Return to customers
      </Link>
    </div>
  );
}

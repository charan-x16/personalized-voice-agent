import styles from "./status.module.css";

export default function ProductLoading() {
  return (
    <div className={styles.loading} role="status" aria-live="polite">
      <span className="sr-only">Loading your workspace</span>
      <div className={styles.loadingHeader}>
        <span />
        <span />
      </div>
      <div className={styles.loadingHero}>
        <span />
        <span />
      </div>
      <div className={styles.loadingMetrics}>
        <span />
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

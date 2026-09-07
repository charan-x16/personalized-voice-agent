import styles from "./customers.module.css";

export default function CustomersLoading() {
  return (
    <div className={styles.loading} role="status" aria-live="polite">
      <span className="sr-only">Loading customer directory</span>
      <div className={styles.loadingTitle} aria-hidden="true"><span /><span /></div>
      <div className={styles.loadingMetrics} aria-hidden="true">
        <span /><span /><span /><span />
      </div>
      <div className={styles.loadingDirectory} aria-hidden="true">
        <span className={styles.loadingToolbar} />
        <span /><span /><span /><span />
      </div>
    </div>
  );
}

import styles from "../customers.module.css";

export default function CustomerDetailLoading() {
  return (
    <div className={`${styles.loading} ${styles.detailLoading}`} role="status" aria-live="polite">
      <span className="sr-only">Loading customer profile</span>
      <span className={styles.loadingBack} aria-hidden="true" />
      <div className={styles.loadingProfile} aria-hidden="true">
        <span />
        <div><span /><span /></div>
      </div>
      <div className={styles.loadingMetrics} aria-hidden="true">
        <span /><span /><span /><span />
      </div>
      <div className={styles.loadingDetailGrid} aria-hidden="true">
        <span /><span />
      </div>
    </div>
  );
}

import { SkeletonText } from "@/components/ds/Skeleton";
import styles from "./news.module.css";

/** Stable newsroom-shaped loading, before the live shared feed resolves. */
export default function Loading() {
  return (
    <div className={styles.page} aria-busy="true" aria-label="Loading news">
      <div className={styles.loadingTitle}>
        <SkeletonText lines={2} />
      </div>
      <div className={styles.loadingLead}>
        <SkeletonText lines={4} />
      </div>
      <SkeletonText lines={6} />
    </div>
  );
}

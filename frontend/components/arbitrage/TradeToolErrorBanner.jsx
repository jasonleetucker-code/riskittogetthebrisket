"use client";

// A failed trade-tool request: the readable message first; the backend's
// machine code and any technical text (a bridge's "fetch failed") only as
// details (lib/trade-finder-errors).

import { Banner } from "@/components/ds";
import styles from "./trade-tool-notes.module.css";

export default function TradeToolErrorBanner({ failure, title }) {
  if (!failure || !failure.message) return null;
  return (
    <Banner tone="negative" title={title}>
      {failure.message}
      {failure.code ? (
        <span className={styles.errorCode}>
          {" "}
          (code: <code>{failure.code}</code>)
        </span>
      ) : null}
      {failure.detail ? (
        <span className={styles.errorCode} data-testid="trade-tool-error-detail">
          {" "}
          (details: {failure.detail})
        </span>
      ) : null}
    </Banner>
  );
}

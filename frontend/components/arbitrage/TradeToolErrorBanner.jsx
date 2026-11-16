"use client";

// A failed trade-tool request: the readable message first, the backend's
// machine code only as a detail (lib/trade-finder-errors).

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
    </Banner>
  );
}

"use client";

// A failed trade-tool request: the readable message first; the backend's
// machine code and any technical text (a bridge's "fetch failed") only as
// details (lib/trade-finder-errors).
//
// `failure` is a classified failure `{message, code, detail, retryable}`, or a
// plain sentence — a caller's own input check ("Enter at least 3 players"),
// which a retry cannot change, so a string is never retryable.
//
// `onRetry` (optional) adds a "Try again" that re-issues the failed request.
// It is withheld when the failure says `retryable: false` — a deterministic
// refusal (an unknown team, an invalid request) fails identically on a retry,
// and offering one implies the answer might change.

import { Banner, Button } from "@/components/ds";
import styles from "./trade-tool-notes.module.css";

export default function TradeToolErrorBanner({ failure, title, onRetry }) {
  const f = typeof failure === "string" ? { message: failure, retryable: false } : failure;
  if (!f || !f.message) return null;
  const showRetry = typeof onRetry === "function" && f.retryable !== false;
  return (
    <Banner tone="negative" title={title}>
      {f.message}
      {f.code ? (
        <span className={styles.errorCode}>
          {" "}
          (code: <code>{f.code}</code>)
        </span>
      ) : null}
      {f.detail ? (
        <span className={styles.errorCode} data-testid="trade-tool-error-detail">
          {" "}
          (details: {f.detail})
        </span>
      ) : null}
      {showRetry ? (
        <>
          {" "}
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </>
      ) : null}
    </Banner>
  );
}

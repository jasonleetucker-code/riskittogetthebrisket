/**
 * FailureState — render a CLASSIFIED failure, not a sentence.
 *
 * WHY IT EXISTS
 * ─────────────
 * The audit found eight high-use routes rendering four different
 * situations identically. `/settings` printed a bare red `<p>` with no
 * role and no primitive. `/rosters` rendered errors through
 * `EmptyState title="Error"`. `/league` rendered them through the EMPTY
 * primitive, so "this league has no data" and "the request failed" looked
 * the same. `/admin` asserted an authorization cause for every failure
 * including a 500 and a dropped connection. `/login` turned a 429 or a
 * 503 into "Invalid username or password."
 *
 * None of that is a styling problem. It is that the failure arrived as a
 * string, so the only thing a page could do with it was print it.
 * `lib/contract-failure.js` turns it back into a state; this renders that
 * state, and one component doing it is what keeps the eight routes saying
 * the same thing for the same reason.
 *
 * THE DISTINCTIONS IT REFUSES TO COLLAPSE
 * ───────────────────────────────────────
 *   empty        the request worked and there is nothing yet — NOT a
 *                fault, and never voiced as one
 *   degraded     the server is up and declining for a stated reason
 *   unavailable  the server is not answering
 *   auth         signed out
 *   forbidden    signed in, not permitted — a different sentence, and no
 *                "retry" button, because retrying cannot help
 *
 * TONE IS A JUDGEMENT, NOT A COLOUR
 * ─────────────────────────────────
 * `empty` renders `info`, so the calm/urgent split matches whether
 * anything is actually wrong. `Banner` maps that onto `role="status"`
 * versus `role="alert"`, so a screen reader is interrupted for a failure
 * and not for a pipeline that is still warming up.
 */
"use client";

import React from "react";
import { Banner } from "./Banner";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

/**
 * Per-kind presentation.
 *
 * `title` is what happened. `hint` is what the reader can do about it —
 * omitted entirely when the honest answer is "nothing", because a
 * suggestion that cannot work is worse than none.
 */
const PRESENTATION = {
  empty: {
    tone: "info",
    title: "No data yet",
    hint: "The pipeline may still be starting up. This usually clears on its own.",
    canRetry: true,
  },
  no_data: {
    tone: "warning",
    title: "No data received",
    hint: "The server answered without a payload.",
    canRetry: true,
  },
  auth: {
    tone: "warning",
    title: "Sign-in required",
    hint: "Your session has expired.",
    canRetry: false,
  },
  forbidden: {
    tone: "warning",
    title: "Not available to this account",
    // Deliberately no hint and no retry: this is a permissions answer,
    // and inviting a retry implies the answer might change.
    hint: "",
    canRetry: false,
  },
  degraded: {
    tone: "warning",
    title: "Serving degraded",
    hint: "The server is up and declining this request for the reason above.",
    canRetry: true,
  },
  unavailable: {
    tone: "negative",
    title: "Service unavailable",
    hint: "The backend is not answering right now.",
    canRetry: true,
  },
  rate_limited: {
    tone: "warning",
    title: "Rate limited",
    hint: "Too many requests. Wait a moment before retrying.",
    canRetry: true,
  },
  offline: {
    tone: "negative",
    title: "Could not reach the server",
    hint: "Check your connection.",
    canRetry: true,
  },
  server: {
    tone: "negative",
    title: "Server error",
    hint: "",
    canRetry: true,
  },
  error: {
    tone: "negative",
    title: "Something went wrong",
    hint: "",
    canRetry: false,
  },
};

/**
 * @param {object} props
 * @param {{kind:string, code?:string, message?:string, retryable?:boolean}} props.failure
 * @param {() => void} [props.onRetry]
 * @param {"banner"|"block"} [props.variant] banner sits above surviving
 *   content; block replaces it.
 * @param {string} [props.context] what could not be loaded, e.g. "rankings"
 */
export function FailureState({
  failure,
  onRetry,
  variant = "banner",
  context = "",
  className = "",
}) {
  if (!failure) return null;
  const spec = PRESENTATION[failure.kind] || PRESENTATION.error;
  const title = context ? `${spec.title} — ${context}` : spec.title;

  // The server's own words come FIRST when it gave any. A stated reason
  // ("scoring identity could not be proven for this league") is more use
  // than our generic sentence, and dropping it in favour of a friendlier
  // one is how a degraded state becomes indistinguishable from an outage.
  const detail = failure.message || "";
  const showRetry = Boolean(onRetry) && spec.canRetry && failure.retryable !== false;

  if (variant === "block") {
    return (
      <EmptyState
        title={title}
        description={[detail, spec.hint].filter(Boolean).join(" ")}
        action={
          showRetry ? (
            <Button variant="secondary" size="sm" onClick={onRetry}>
              Try again
            </Button>
          ) : undefined
        }
        className={className}
      />
    );
  }

  return (
    <Banner tone={spec.tone} title={title} className={className}>
      {detail ? <span>{detail}</span> : null}
      {detail && spec.hint ? " " : null}
      {spec.hint ? <span>{spec.hint}</span> : null}
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

export default FailureState;

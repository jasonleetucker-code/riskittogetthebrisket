"use client";

// The recommendation (directive Phase 9).  The headline, message and reason
// text are the backend's fixed category copy and are rendered VERBATIM —
// this component chooses only a tone and an icon, and the category stays
// readable without colour (icon + words).  It never shows a value, a score,
// a margin or a confidence number, because it never receives one.

import { useEffect, useRef } from "react";
import { Button } from "@/components/ds/Button";
import { Icon } from "@/components/ds/Icon";
import { CATEGORY_TONE } from "@/lib/trade-advisor";
import { AdvisorSummary } from "./_advisor-summary.jsx";
import styles from "./trade-advisor.module.css";

const TONE_ICON = { positive: "check", neutral: "dash", warning: "warning" };

export function AdvisorResult({ state, teams, onEdit, onNewTrade, onStartOver, onRetry, retryDisabled }) {
  const result = state.result;
  const headingRef = useRef(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, [result]);
  if (!result) return null;
  const unavailable = result.category === "UNAVAILABLE";
  const tone = CATEGORY_TONE[result.category] || "neutral";
  const icon = unavailable ? "info" : TONE_ICON[tone];
  const labels = new Map(state.legs.map((l) => [l.id, l.label]));
  const notEvaluable = (result.unavailableAssetIds || []).map((id) => labels.get(id)).filter(Boolean);
  const showReason = result.reasonText && result.reasonText !== result.message;
  // Retrying cannot change a "more than two teams" answer.
  const showRetry = unavailable && result.reasonCode !== "multi_team_unsupported";

  return (
    <section className={styles.result} aria-labelledby="advisor-result-heading" data-testid="advisor-result">
      <h2 className={styles.resultHeading} id="advisor-result-heading" tabIndex={-1} ref={headingRef}>
        Trade analysis
      </h2>
      <AdvisorSummary state={state} teams={teams} youLabel="Your team" />
      <div className={styles.verdict} data-tone={tone} data-category={result.category}>
        <Icon name={icon} size={18} className={styles.verdictIcon} />
        <div>
          <p className={styles.verdictEyebrow}>{state.teamCount > 2 ? "Your team's recommendation" : "Recommendation"}</p>
          <p className={styles.verdictHeadline} data-testid="advisor-headline">
            {result.headline}
          </p>
          <p className={styles.verdictMessage}>{result.message}</p>
          {showReason ? <p className={styles.verdictMessage}>{result.reasonText}</p> : null}
          {notEvaluable.length ? (
            <p className={styles.verdictMessage}>Can&apos;t be evaluated right now: {notEvaluable.join(", ")}.</p>
          ) : null}
        </div>
      </div>
      {/* One polite announcement per result. */}
      <p className="ds-visually-hidden" role="status" aria-live="polite">
        {`${result.headline}. ${result.message}`}
      </p>
      {!unavailable && state.teamCount === 2 ? (
        <p className={styles.note}>
          Two-team recommendations account for your team&apos;s roster and lineup, its competitive outlook and any
          players you would have to release to make room.
        </p>
      ) : null}
      <div className={styles.resultActions}>
        {showRetry ? (
          <Button variant="primary" onClick={onRetry} disabled={retryDisabled}>
            Try again
          </Button>
        ) : null}
        <Button variant={showRetry ? "secondary" : "primary"} onClick={onEdit}>
          Edit trade
        </Button>
        <Button onClick={onNewTrade}>New trade</Button>
        <Button variant="ghost" onClick={onStartOver}>
          Start over
        </Button>
      </div>
    </section>
  );
}

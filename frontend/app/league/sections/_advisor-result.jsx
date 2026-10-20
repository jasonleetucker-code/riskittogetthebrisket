"use client";

// The fairness result (owner amendment 2026-10-20: the public advisor
// answers "Is this trade fair?" — FAIR TRADE / NOT FAIR / UNABLE TO
// DETERMINE — and never says to accept or decline anything).
//
// ONE server response carries every participating team's result plus the
// overall result (spec §4.3).  This component shows the overall result and
// an all-team list, then lets the reader switch to any team's own result —
// a different row of the same response, no new request and nothing
// recomputed.  Labels, reason text and the multi-team note are the
// server's fixed copy rendered VERBATIM; this component chooses only a tone
// and an icon, and every result stays readable without colour (icon +
// words).  It never shows a value, a gap, a margin or a confidence number,
// because it never receives one.

import { useEffect, useRef } from "react";
import { Button } from "@/components/ds/Button";
import { Badge } from "@/components/ds/Badge";
import { Icon } from "@/components/ds/Icon";
import { Tabs, tabId, tabPanelId } from "@/components/ds/Tabs";
import { RESULT_SHORT, RESULT_TONE, tradeSummary } from "@/lib/trade-advisor";
import { TeamFlows } from "./_advisor-summary.jsx";
import styles from "./trade-advisor.module.css";

const TONE_ICON = { positive: "check", warning: "warning", neutral: "info" };
const BADGE_TONE = { positive: "positive", warning: "warning", neutral: "neutral" };
const VIEW_PREFIX = "advisor-view";

function Verdict({ result, label, reasonText, note, eyebrow, testid }) {
  const tone = RESULT_TONE[result] || "neutral";
  return (
    <div className={styles.verdict} data-tone={tone} data-result={result} data-testid={testid}>
      <Icon name={TONE_ICON[tone]} size={18} className={styles.verdictIcon} />
      <div>
        <p className={styles.verdictEyebrow}>{eyebrow}</p>
        <p className={styles.verdictHeadline} data-testid={testid ? `${testid}-label` : undefined}>
          {label}
        </p>
        {reasonText ? <p className={styles.verdictMessage}>{reasonText}</p> : null}
        {note ? <p className={styles.verdictMessage}>{note}</p> : null}
      </div>
    </div>
  );
}

export function AdvisorResult({ state, teams, onView, onEdit, onNewTrade, onStartOver, onRetry, retryDisabled }) {
  const result = state.result;
  const headingRef = useRef(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, [result]);
  if (!result) return null;

  const flows = new Map(tradeSummary(state, teams).teams.map((t) => [t.rosterId, t]));
  const labels = new Map(state.legs.map((l) => [l.id, l.label]));
  // Slot order: the selected team first, then the order teams were chosen.
  const order = new Map(state.slots.map((rid, i) => [rid, i]));
  const rows = result.teams
    .slice()
    .sort((a, b) => (order.get(a.rosterId) ?? 99) - (order.get(b.rosterId) ?? 99) || a.rosterId - b.rosterId)
    .map((t) => ({ ...t, flows: flows.get(t.rosterId) || null }));
  const nameOf = (row) => (row.flows ? row.flows.name : `Team ${row.rosterId}`);
  const viewed = rows.find((r) => r.rosterId === state.view) || rows[0];
  const viewedAssets = (viewed.unavailableAssetIds || []).map((id) => labels.get(id) || id);
  const overall = result.overall;
  // Retrying can only help a transient "can't evaluate right now".
  const showRetry =
    overall.result === "UNABLE_TO_DETERMINE" && rows.some((r) => r.reasonCode === "evaluation_unavailable");

  return (
    <section className={styles.result} aria-labelledby="advisor-result-heading" data-testid="advisor-result">
      <h2 className={styles.resultHeading} id="advisor-result-heading" tabIndex={-1} ref={headingRef}>
        Is this trade fair?
      </h2>

      <Verdict
        result={overall.result}
        label={overall.label}
        reasonText={overall.reasonText}
        note={overall.note}
        eyebrow={`Overall result · ${rows.length} teams`}
        testid="advisor-overall"
      />

      <div className={styles.teamResults}>
        <h3 className={styles.summaryTeamName} id="advisor-team-results">
          Result for each team
        </h3>
        <ul className={styles.teamResultList} aria-labelledby="advisor-team-results" data-testid="advisor-team-results">
          {rows.map((r) => {
            const tone = RESULT_TONE[r.result] || "neutral";
            return (
              <li key={r.rosterId} className={styles.teamResultRow} data-result={r.result}>
                <span className={styles.teamResultName}>
                  {nameOf(r)}
                  {r.flows?.isYou ? " (your team)" : ""}
                </span>
                <Badge tone={BADGE_TONE[tone]} className={styles.teamResultBadge}>
                  <Icon name={TONE_ICON[tone]} size={12} /> {r.label}
                </Badge>
              </li>
            );
          })}
        </ul>
      </div>

      <div className={styles.perspective}>
        <h3 className={styles.summaryTeamName} id="advisor-view-heading">
          View one team&apos;s result
        </h3>
        <Tabs
          idPrefix={VIEW_PREFIX}
          label="View one team's result"
          tabs={rows.map((r) => ({
            id: String(r.rosterId),
            label: nameOf(r),
            badge: <span className={styles.tabResult}>· {RESULT_SHORT[r.result]}</span>,
          }))}
          active={String(viewed.rosterId)}
          onChange={(id) => onView?.(Number(id))}
        />
        <div
          role="tabpanel"
          id={tabPanelId(VIEW_PREFIX, String(viewed.rosterId))}
          aria-labelledby={tabId(VIEW_PREFIX, String(viewed.rosterId))}
          className={styles.perspectivePanel}
          data-testid="advisor-team-view"
          data-roster={viewed.rosterId}
        >
          <Verdict
            result={viewed.result}
            label={viewed.label}
            reasonText={viewed.reasonText}
            eyebrow={`${nameOf(viewed)}${viewed.flows?.isYou ? " (your team)" : ""}`}
            testid="advisor-team-verdict"
          />
          {viewedAssets.length ? (
            <p className={styles.verdictMessage}>Players or picks concerned: {viewedAssets.join(", ")}.</p>
          ) : null}
          {viewed.flows ? <TeamFlows team={viewed.flows} headingLevel={4} showName={false} /> : null}
        </div>
      </div>

      <p className={styles.note}>
        Each team&apos;s result compares what it sends with what it receives, using our league&apos;s dynasty market. It
        doesn&apos;t consider any team&apos;s roster needs, lineup or plans.
      </p>

      {/* One polite announcement per result. */}
      <p className="ds-visually-hidden" role="status" aria-live="polite">
        {`${overall.label}. ${overall.reasonText || ""}`}
      </p>

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

"use client";

import { Badge, Banner, Panel } from "@/components/ds";
import { buildTeamPlanView } from "@/lib/team-plan";
import styles from "./this-week.module.css";

/**
 * ThisWeekPlan — the body of the home "This week" panel (lazy chunk).
 *
 * Renders an accepted `GET /api/team/plan` payload as-is: context rows
 * (posture, strength, weak spots, core age, draft capital, roster freshness),
 * then the backend's ranked actions IN THE PAYLOAD'S ORDER, each with its
 * kind, subject, the owner's reason, its uncertainty and, behind a
 * disclosure, its evidence and owner.  Every label is text — no state is
 * carried by colour alone — and a missing value reads "not available", never
 * 0.  `lib/team-plan.js` only formats; nothing here ranks or decides.
 */
function PlanAction({ action }) {
  return (
    <li className={styles.planRow}>
      <div className={styles.planHead}>
        {action.rank != null && (
          <span className={`${styles.planRank} ds-tnum`}>{action.rank}.</span>
        )}
        <Badge tone="outline">{action.kindLabel}</Badge>
        <span className={styles.planSubject}>{action.subject}</span>
      </div>
      {action.reason && <p className={styles.planReason}>{action.reason}</p>}
      {action.uncertainty.length > 0 && (
        <p className={styles.planMeta}>
          {action.uncertainty.map((u) => `${u.label}: ${u.text}`).join(" · ")}
        </p>
      )}
      <details className={styles.planEvidence}>
        <summary>Evidence · {action.source}</summary>
        <dl className={styles.planContext}>
          {action.evidence.map((e) => (
            <div key={e.key} className={styles.planContextRow}>
              <dt>{e.label}</dt>
              <dd>{e.text}</dd>
            </div>
          ))}
          {action.owner && (
            <div className={styles.planContextRow}>
              <dt>Computed by</dt>
              <dd className={styles.planOwner}>{action.owner}</dd>
            </div>
          )}
        </dl>
      </details>
    </li>
  );
}

export default function ThisWeekPlan({ plan }) {
  const view = buildTeamPlanView(plan);
  const { freshness, planState } = view;
  const subtitle = [view.teamName, "advisory plan, not a verdict"].filter(Boolean).join(" · ");

  return (
    <Panel className="panel--this-week" title="This week" subtitle={subtitle}>
      <div className={styles.planStack} data-testid="this-week-plan">
        {freshness.stale && (
          <Banner tone="warning" title="Rosters are stale">
            {`This plan reads rosters ${[freshness.ageText, freshness.sourceText ? `from ${freshness.sourceText}` : null]
              .filter(Boolean)
              .join(", ") || "from an older snapshot"}. Every move describes that snapshot, not necessarily today's rosters.`}
          </Banner>
        )}
        {freshness.unknown && (
          <Banner tone="warning" title="Roster freshness unknown">
            The rosters behind this plan have no provable fetch time, so they may not be today&apos;s.
          </Banner>
        )}
        {planState.incomplete && (
          <Banner tone="info" title="Plan incomplete">
            <p className={styles.planNote}>
              Some kinds of move could not be checked. A missing move of these kinds is unknown, not
              &ldquo;nothing to do&rdquo;.
            </p>
            <ul className={styles.planNotes}>
              {planState.unassessed.map((u) => (
                <li key={u.key}>
                  {u.kindLabel}: {u.text}
                </li>
              ))}
            </ul>
          </Banner>
        )}

        <dl className={styles.planContext} aria-label="Team context">
          {view.context.map((row) => (
            <div key={row.key} className={styles.planContextRow}>
              <dt>{row.label}</dt>
              <dd>{row.text}</dd>
            </div>
          ))}
        </dl>

        {view.actions.length > 0 ? (
          <ol className={styles.planList} aria-label="Next moves, in the plan's order">
            {view.actions.map((action) => (
              <PlanAction key={action.key} action={action} />
            ))}
          </ol>
        ) : (
          <p className={styles.planNote}>
            No move to show yet. This is not &ldquo;nothing to do&rdquo;: some checks have not run
            (see &ldquo;Plan incomplete&rdquo;).
          </p>
        )}

        {planState.notAssessable.map((n) => (
          <p key={n.key} className={styles.planNote}>
            {n.kindLabel}s are not assessed: {n.reason}.
          </p>
        ))}
        {planState.unmapped.length > 0 && (
          <p className={styles.planNote}>
            Trade suggestions also found ideas this plan does not list:{" "}
            {planState.unmapped
              .map((u) => (u.count != null ? `${u.label} (${u.count})` : u.label))
              .join(", ")}
            .
          </p>
        )}
      </div>
    </Panel>
  );
}

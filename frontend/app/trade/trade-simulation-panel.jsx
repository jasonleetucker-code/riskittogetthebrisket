"use client";

/**
 * trade-simulation-panel.jsx — the "Simulate impact" result panel.
 *
 * Split out of ./trade-sections.jsx so /trade can load it on demand
 * (React.lazy in app/trade/page.jsx): it renders only after the user runs a simulation, so it has no
 * business in the page's first-load chunk.
 * Pure presentation, moved verbatim — no trade math lives here.
 */

import { useId } from "react";
import { Badge, Banner, Button, DataTable, Movement, Panel, StatTile } from "@/components/ds";
import styles from "./trade.module.css";

function fmtSigned(n) {
  const v = Math.round(Number(n) || 0);
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString()}`;
}

// ── Simulation impact ─────────────────────────────────────────────────

const VERDICT_TONE = {
  accept: "positive",
  "lean accept": "positive",
  neutral: "neutral",
  "lean decline": "negative",
  decline: "negative",
};

/**
 * `finalRosterSimulation` refusal copy, keyed by the backend's own
 * `unavailableReason`.  The backend refuses for reasons that mean
 * genuinely different things to a user, so they are not collapsed into
 * one "unavailable" line.
 */
const FINAL_ROSTER_UNAVAILABLE_COPY = {
  capacity_uncertain:
    "taxi occupancy is unknown, so the forced-drop set is a range rather than a determined set — see Roster capacity above",
  starter_slots_unresolved:
    "the league's starting slots did not resolve, so no lineup could be solved",
};

/**
 * Why the final roster was not simulated.
 *
 * Reads BOTH shapes the backend can stamp: `{available: false,
 * unavailableReason}` for a deliberate refusal, and `{unavailable:
 * "<ExcType>"}` for an error — the second carries no `available` key at
 * all, which is why the caller tests `available === true` rather than
 * `available !== false`.
 */
function finalRosterUnavailableText(frs) {
  const reason = frs?.unavailableReason || frs?.unavailable || "reason not reported";
  return `Not simulated — ${FINAL_ROSTER_UNAVAILABLE_COPY[reason] || reason}.`;
}

/** Backend-stamped number for display. Missing stays missing, never 0. */
function strengthText(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

export function SimulationPanel({ simResult, simError, selectedTeam, onReset }) {
  if (!simResult && !simError) return null;

  const teamName =
    simResult?.team?.name || selectedTeam?.name || "your team";
  const ti = simResult?.teamImpact;
  const starterEntries = Object.entries(ti?.starterValueDelta || {}).filter(
    ([, v]) => v !== 0,
  );
  const unresolved = [
    ...(simResult?.unresolvedIn || []),
    ...(simResult?.unresolvedOut || []),
  ];
  const rc = simResult?.rosterCapacity;
  // V1-45 / V1-42. `rosterCapacity` says WHO must go; this says what the
  // roster IS once they have — the lineup re-solved over the post-trade,
  // post-cleanup roster. Absent (not null) whenever there is no resolved
  // team, and absent must render nothing at all.
  const frs = simResult?.finalRosterSimulation;

  return (
    <Panel
      title={`Impact on ${teamName}`}
      headingLevel={2}
      actions={
        <Button variant="ghost" size="sm" onClick={onReset}>
          Clear simulation
        </Button>
      }
    >
      {simError ? (
        <Banner tone="negative" title="Simulation failed">
          {simError}
        </Banner>
      ) : null}

      {simResult ? (
        <>
          <div className={styles.simGrid}>
            <StatTile
              label="Before"
              value={Math.round(simResult.before?.totalValue || 0).toLocaleString()}
            />
            <StatTile
              label="After"
              value={Math.round(simResult.after?.totalValue || 0).toLocaleString()}
            />
            <StatTile
              label="Change"
              value={fmtSigned(simResult.delta?.totalValue)}
              movement={
                <Movement
                  delta={simResult.delta?.totalValue || 0}
                  format={(n) => n.toLocaleString()}
                />
              }
            />
          </div>

          {/* What Before/After/Change ARE (src/api/trade_simulator.py
              _aggregate): a plain sum of canonical board values — no Value
              Adjustment, unpriced players as 0, and no forced release
              subtracted.  Next to a VA-adjusted meter that is a different
              quantity, so it is named. */}
          <p className={styles.suggestMeta}>
            Roster totals: summed board values, before Value Adjustment. A
            forced release is not subtracted here.
          </p>

          <div className={styles.simPosGrid} style={{ marginTop: "var(--space-3)" }}>
            {["QB", "RB", "WR", "TE"].map((pos) => {
              const row = simResult.delta?.byPosition?.[pos];
              if (!row) return null;
              return (
                <StatTile
                  key={pos}
                  label={pos}
                  value={fmtSigned(row.value)}
                  meta={row.count !== 0 ? `${row.count > 0 ? "+" : ""}${row.count} players` : null}
                />
              );
            })}
          </div>

          {ti ? (
            <div className={styles.simSection} style={{ marginTop: "var(--space-3)" }}>
              <div className={styles.simSectionHead}>
                <span className={styles.simSectionTitle}>Roster fit</span>
                <span className={styles.simVerdict}>
                  <Badge tone={VERDICT_TONE[ti.verdict] || "neutral"}>{ti.verdict}</Badge>
                  <span className={styles.simScore}>
                    {ti.compositeScore >= 0 ? "+" : ""}
                    {ti.compositeScore.toFixed(1)}
                  </span>
                </span>
              </div>
              <div className={styles.simGrid}>
                <StatTile
                  label="Fit"
                  value={`${ti.fitScore >= 0 ? "+" : ""}${ti.fitScore.toFixed(1)}`}
                />
                <StatTile
                  label="Equity"
                  value={`${ti.equityScore >= 0 ? "+" : ""}${ti.equityScore.toFixed(1)}`}
                />
                {/* Wave B: window fit follows the canonical Competitive
                    Posture (C7-POST-01). Without one it is NOT computed —
                    shown as unavailable, never as a neutral 0.00. */}
                <StatTile
                  label={ti.competitivePosture || "Window"}
                  value={
                    typeof ti.windowFit === "number"
                      ? `${ti.windowFit >= 0 ? "+" : ""}${ti.windowFit.toFixed(2)}`
                      : "—"
                  }
                  meta={
                    typeof ti.windowFit === "number" ? "window fit" : "posture unavailable"
                  }
                />
              </div>
              {starterEntries.length > 0 ? (
                <div className={styles.simStarterGrid}>
                  {starterEntries.map(([pos, dv]) => (
                    <StatTile
                      key={pos}
                      label={`${pos} starter`}
                      value={fmtSigned(dv)}
                      bare
                    />
                  ))}
                </div>
              ) : null}
              {ti.rationale?.length > 0 ? (
                <ul className={styles.simRationale}>
                  {ti.rationale.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              ) : null}
              {ti.redundancy?.length > 0 ? (
                <Banner tone="warning">
                  Redundant: {ti.redundancy.map((r) => `${r.name} (${r.pos})`).join(", ")}
                </Banner>
              ) : null}
            </div>
          ) : null}

          {rc && rc.requiresDrops === true ? (
            <Banner tone="warning" title="Roster capacity">
              {`Forces ${rc.forcedDrops.length} release${rc.forcedDrops.length === 1 ? "" : "s"}` +
                (rc.rosterLimit != null ? ` to fit the ${rc.rosterLimit}-man limit` : "") +
                (rc.forcedDropValue != null
                  ? ` — ${Math.round(rc.forcedDropValue).toLocaleString()} value released`
                  : "") +
                (rc.unpricedForcedDrops > 0
                  ? ` (plus ${rc.unpricedForcedDrops} unpriced, not counted)`
                  : "") +
                (rc.forcedDropsAreUpperBound ? " (worst case; taxi occupancy uncertain)" : "") +
                (rc.ladderExhausted ? " — no fully legal cleanup found" : "")}
              {rc.forcedDrops.length > 0 ? (
                <ul className={styles.simRationale}>
                  {rc.forcedDrops.map((d) => (
                    <li key={d.playerId || d.name}>
                      {d.name} ({d.position}) —{" "}
                      {d.value != null ? Math.round(d.value).toLocaleString() : "unpriced"}
                    </li>
                  ))}
                </ul>
              ) : null}
            </Banner>
          ) : null}

          {/* The simulator publishes {unavailable, notes} when capacity
              could not be computed.  Rendering nothing would read exactly
              like "fits" — absent and zero must not look the same. */}
          {rc && rc.unavailable ? (
            <Banner tone="neutral" title="Roster capacity">
              Roster capacity could not be checked for this trade, so any forced
              release is unknown — not zero.
            </Banner>
          ) : null}

          {rc && rc.requiresDrops === null ? (
            <Banner tone="neutral" title="Roster capacity">
              {rc.rosterLimit == null
                ? "Roster capacity unknown for this league."
                : "Roster capacity uncertain — taxi occupancy unknown; this trade may or may not require a release."}
            </Banner>
          ) : null}

          {/* Final roster — renders AFTER the capacity blocks on purpose:
              the backend's own `capacity_uncertain` note says "see
              rosterCapacity", so it must read after what it refers to.
              Pure display of backend stamps; nothing here is derived. */}
          {frs ? (
            frs.available === true ? (
              <div className={styles.simSection} style={{ marginTop: "var(--space-3)" }}>
                <div className={styles.simSectionHead}>
                  <span className={styles.simSectionTitle}>Final roster</span>
                </div>
                <div className={styles.simGrid}>
                  <StatTile label="Strength before" value={strengthText(frs.strengthBefore?.total)} />
                  <StatTile label="Strength after" value={strengthText(frs.strengthAfter?.total)} />
                  <StatTile
                    label="Strength change"
                    /* The BACKEND's delta. Never `after - before`: this
                       file computes no trade math, and a client-side
                       subtraction would silently republish a different
                       quantity under a canonical field's name. */
                    value={
                      Number.isFinite(Number(frs.strengthDelta))
                        ? fmtSigned(frs.strengthDelta)
                        : "—"
                    }
                  />
                </div>

                {frs.promotions?.length > 0 ? (
                  <ul className={styles.simRationale}>
                    {frs.promotions.map((m) => (
                      <li key={`promo-${m.playerId || m.name}`}>
                        Promoted: {m.name} ({m.position}) →{" "}
                        {m.slotAfter || "lineup"}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {frs.displacements?.length > 0 ? (
                  <ul className={styles.simRationale}>
                    {frs.displacements.map((m) => (
                      <li key={`disp-${m.playerId || m.name}`}>
                        Displaced: {m.name} ({m.position}) — {m.slotBefore || "lineup"} → bench
                      </li>
                    ))}
                  </ul>
                ) : null}

                {/* Both directions, with equal weight. RosterSimulation's
                    own docstring: "A simulation that only showed what
                    improved would be an advocacy tool." */}
                {frs.needsFixed?.length > 0 || frs.needsCreated?.length > 0 ? (
                  <ul className={styles.simRationale}>
                    {frs.needsFixed?.length > 0 ? (
                      <li>Needs closed: {frs.needsFixed.join(", ")}</li>
                    ) : null}
                    {frs.needsCreated?.length > 0 ? (
                      <li>Needs opened: {frs.needsCreated.join(", ")}</li>
                    ) : null}
                  </ul>
                ) : null}

                {frs.cleanupApplied?.length > 0 ? (
                  <p className={styles.suggestMeta}>
                    {`Solved after ${frs.cleanupApplied.length} required release` +
                      `${frs.cleanupApplied.length === 1 ? "" : "s"} — named under Roster capacity.`}
                  </p>
                ) : null}

                {frs.unpricedIncoming?.length > 0 ? (
                  <p className={styles.suggestMeta}>
                    Incoming, not priced by the board: {frs.unpricedIncoming.join(", ")}
                  </p>
                ) : null}

                {frs.outgoingNotFound?.length > 0 ? (
                  <p className={styles.suggestMeta}>
                    Sent but not found on this roster: {frs.outgoingNotFound.join(", ")}
                  </p>
                ) : null}

                {frs.cleanupIsUpperBound ? (
                  <Banner tone="warning">
                    The releases this was solved against are a worst case, so this final
                    roster is one of a range rather than a determined set.
                  </Banner>
                ) : null}
              </div>
            ) : (
              <Banner tone="neutral" title="Final roster">
                {finalRosterUnavailableText(frs)}
              </Banner>
            )
          ) : null}

          {unresolved.length > 0 ? (
            <Banner tone="warning" title="Unresolved assets">
              {unresolved.join(", ")}
            </Banner>
          ) : null}

          <p className={styles.suggestMeta} style={{ marginTop: "var(--space-2)" }}>
            Equity (receiving − sending): {fmtSigned(simResult.equity)}
          </p>

          {/* Secondary context, deliberately AFTER every verdict-bearing
              block: exposure feeds no value, equity or verdict
              (C2-EXP-01), so it must not read as part of the grade. */}
          <NflExposureSection exposure={simResult.nflExposure} />
        </>
      ) : null}
    </Panel>
  );
}

// ── NFL team exposure (C2-EXP-01) ─────────────────────────────────────

/**
 * Backend share (0–100 scale, already a percentage) for display.
 * Missing stays missing: `null` is an UNMEASURED share, never 0%.
 */
function exposurePct(v) {
  if (v == null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : "—";
}

/** Backend Herfindahl index (0–10,000) for display; missing stays missing. */
function exposureHhi(v) {
  if (v == null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

/** Magnitude formatter for <Movement>: percentage points, never a bare 0.0. */
function ppMagnitude(m) {
  return m > 0 && m < 0.05 ? "<0.1 pp" : `${m.toFixed(1)} pp`;
}

function exposureIds(ids) {
  return Array.isArray(ids) ? ids.filter(Boolean) : [];
}

const EXPOSURE_SCOPE_COPY = {
  full_roster: "Share of full-roster board value",
};

const EXPOSURE_MOVE_COLUMNS = [
  {
    key: "team",
    header: "NFL team",
    render: (r) => (r.isFranchise === false ? `${r.team} (not an NFL franchise)` : r.team),
  },
  { key: "shareBefore", header: "Before", numeric: true, render: (r) => exposurePct(r.shareBefore) },
  { key: "shareAfter", header: "After", numeric: true, render: (r) => exposurePct(r.shareAfter) },
  {
    key: "delta",
    header: "Change",
    numeric: true,
    // The BACKEND's delta, in percentage points — never after − before
    // recomputed here.
    render: (r) => {
      const d = Number(r.delta);
      if (r.delta == null || !Number.isFinite(d)) return "—";
      const words = ppMagnitude(Math.abs(d)).replace("pp", "percentage points");
      return (
        <Movement
          delta={d}
          format={ppMagnitude}
          srLabel={d === 0 ? "unchanged" : `${d > 0 ? "up" : "down"} ${words}`}
        />
      );
    },
  },
];

const EXPOSURE_CONCENTRATION_COLUMNS = [
  { key: "measure", header: "Measure" },
  { key: "before", header: "Before", numeric: true },
  { key: "after", header: "After", numeric: true },
];

/**
 * "NFL team exposure" — value-weighted NFL-franchise share of the team's
 * roster before → after the simulated trade (`nflExposure` on
 * `POST /api/trade/simulate`, owner `src/roster_intel/exposure.py`).
 *
 * PURE RENDERER: every share, delta and concentration figure is a backend
 * stamp; nothing is summed, differenced or re-derived here. Collapsed by
 * default and labelled as context — the owner ruled exposure never
 * influences the grade, so it must not present as part of the verdict.
 *
 * States: absent (render nothing), `unavailable`, populated with moves,
 * populated with no team moved, and coverage gaps (`unpricedIds`,
 * `unknownTeamIds`, `outgoingNotOnRoster`), which are always named —
 * missing is never zero.
 */
export function NflExposureSection({ exposure }) {
  const headingId = useId();
  if (!exposure || typeof exposure !== "object") return null;

  const heading = (
    <div className={styles.simSectionHead}>
      <h3 id={headingId} className={`${styles.simSectionTitle} ${styles.exposureTitle}`}>
        NFL team exposure
      </h3>
      <span className={styles.suggestMeta}>Context only — not part of the verdict</span>
    </div>
  );

  const before = exposure.before;
  const after = exposure.after;
  if (exposure.unavailable || !before || !after) {
    const note = exposureIds(exposure.notes)[0];
    return (
      <section className={styles.simSection} aria-labelledby={headingId} data-testid="nfl-exposure">
        {heading}
        <p className={styles.suggestMeta}>
          {`Unavailable — ${note || "NFL-team exposure could not be computed for this trade"}.`}
          {exposure.unavailable ? ` (${exposure.unavailable})` : ""}
        </p>
      </section>
    );
  }

  const moved = Array.isArray(exposure.moved)
    ? exposure.moved
    : Array.isArray(exposure.changes)
      ? exposure.changes
      : [];
  const gaps = [
    ["Not priced by the board — excluded, never counted as zero (before)", exposureIds(before.unpricedIds)],
    ["Not priced by the board — excluded, never counted as zero (after)", exposureIds(after.unpricedIds)],
    ["Priced, but NFL team unknown — excluded (before)", exposureIds(before.unknownTeamIds)],
    ["Priced, but NFL team unknown — excluded (after)", exposureIds(after.unknownTeamIds)],
    ["Sent but not on this roster — frees nothing", exposureIds(exposure.outgoingNotOnRoster)],
  ].filter(([, ids]) => ids.length > 0);

  const concentration = [
    {
      measure: "Largest single team",
      before: exposurePct(before.topFranchiseShare),
      after: exposurePct(after.topFranchiseShare),
    },
    {
      measure: "Concentration index (HHI, 0–10,000)",
      before: exposureHhi(before.franchiseHHI),
      after: exposureHhi(after.franchiseHHI),
    },
  ];

  const summary =
    moved.length > 0
      ? `Show ${moved.length} team${moved.length === 1 ? "" : "s"} that moved`
      : "Show detail — no team's share changed";

  return (
    <section className={styles.simSection} aria-labelledby={headingId} data-testid="nfl-exposure">
      {heading}
      {gaps.length > 0 ? (
        <p className={styles.suggestMeta}>
          Coverage incomplete — some players are excluded; they are named in the detail.
        </p>
      ) : null}
      <details>
        <summary className={styles.exposureSummary}>{summary}</summary>
        <div className={styles.exposureBody}>
          <p className={styles.suggestMeta}>
            {EXPOSURE_SCOPE_COPY[exposure.scope] ||
              `Share of board value${exposure.scope ? ` (${exposure.scope})` : ""}`}
            , before → after the trade as entered. Draft picks carry no NFL team and are not
            included.
          </p>
          <DataTable
            columns={EXPOSURE_MOVE_COLUMNS}
            rows={moved}
            rowKey="team"
            density="compact"
            caption="NFL team share of roster value, before and after the trade"
            emptyState={
              <p className={styles.suggestMeta}>No NFL team&apos;s share of roster value changed.</p>
            }
          />
          <DataTable
            columns={EXPOSURE_CONCENTRATION_COLUMNS}
            rows={concentration}
            rowKey="measure"
            density="compact"
            caption="Roster concentration across NFL teams, before and after the trade"
          />
          {gaps.length > 0 ? (
            <ul className={styles.simRationale}>
              {gaps.map(([label, ids]) => (
                <li key={label}>
                  {label}: {ids.join(", ")}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </details>
    </section>
  );
}

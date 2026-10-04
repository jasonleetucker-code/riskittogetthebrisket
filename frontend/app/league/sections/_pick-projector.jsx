"use client";

// PickProjectorPanel — where future picks are projected to land.
//
// Backs onto /api/ros/pick-projections, which reads the league's season
// simulation under the canonical draft-order rule (worst final record picks
// first, ties broken by lower Points For) and joins it against live pick
// ownership. Team Strength does not decide the order. Only the class drafted
// after the simulated season gets a slot; later classes, and leagues with no
// recorded rule or no fresh simulation, come back with projectedSlot null and
// a named reason — rendered as such, never as a guessed slot.
//
// Projection/context ONLY. Blended pick values come from the canonical
// pipeline (rookie-pool tethering + the multiplicative future-year
// discount) and are untouched here — the panel says where a pick is
// expected to land, never what it is worth. Mixing the two would put a
// second, unreviewed valuation next to the real one.

import { useEffect, useState } from "react";
import {
  PICK_OWNERSHIP_UNAVAILABLE,
  PICK_OWNERSHIP_UNAVAILABLE_ERROR,
  PICK_OWNERSHIP_UNAVAILABLE_LABEL,
  describePickOwnershipReason,
} from "@/lib/pick-ownership";

const CONFIDENCE_STYLE = {
  high: { color: "var(--green)", label: "high" },
  medium: { color: "var(--cyan)", label: "medium" },
  low: { color: "var(--muted)", label: "low" },
};

// The backend's degraded state is 200-with-error by that router's
// convention, and it is ordinary rather than exceptional: an unreachable
// Sleeper. Rendering an alarming failure card for it would train the reader
// to ignore the panel.  (No slot forecast is NOT an error: the picks still
// come back, each with its reason.)
const QUIET_ERRORS = new Set(["no_teams"]);

export function confidenceStyle(confidence) {
  return CONFIDENCE_STYLE[confidence] || CONFIDENCE_STYLE.low;
}

// Why a pick has no projected slot (backend slotForecastUnavailableReason).
const SLOT_FORECAST_REASON_TEXT = {
  class_beyond_simulated_season:
    "Only next season's draft is forecast; this class is further out.",
  no_draft_order_rule_for_league:
    "This league has no recorded draft-order rule, so no slot is forecast.",
  no_fresh_season_simulation:
    "No current season simulation is available yet.",
  season_simulation_unsimulable:
    "The season can't be simulated right now (for example before games start, or between seasons).",
  simulation_published_no_slot_distribution:
    "The season simulation did not publish draft-slot odds.",
  simulation_rule_differs_from_league_rule:
    "The season simulation used a different draft-order rule than this league's.",
  simulation_owner_join_incomplete:
    "The season simulation and the league's current teams don't match up yet.",
  simulated_season_unknown: "The simulated season is unknown.",
  class_before_simulated_season:
    "This draft comes before the simulated season, so it is not forecast.",
  originating_team_not_in_simulation:
    "The original team is not in the season simulation.",
};

/** Plain-language reason a pick carries no projected slot, or null. */
export function slotForecastReasonText(reason) {
  if (!reason) return null;
  // "season_simulation_unsimulable:<why>" carries the simulation's own reason.
  const base = String(reason).split(":")[0];
  return SLOT_FORECAST_REASON_TEXT[base] || "No slot forecast is available.";
}

/**
 * The reason projections were REFUSED because pick ownership is unknown
 * (failed /traded_picks), or null.  Unlike the QUIET_ERRORS above this is
 * not a steady state: hiding it would make "we could not see who owns the
 * picks" look exactly like "no future picks exist", so the panel says so.
 */
export function projectionOwnershipUnavailableReason(data) {
  if (!data || typeof data !== "object") return null;
  const meta = data.meta || {};
  if (meta.pickOwnershipState === PICK_OWNERSHIP_UNAVAILABLE) {
    return meta.pickOwnershipReason || PICK_OWNERSHIP_UNAVAILABLE;
  }
  if (data.error === PICK_OWNERSHIP_UNAVAILABLE_ERROR) {
    return meta.pickOwnershipReason || PICK_OWNERSHIP_UNAVAILABLE;
  }
  return null;
}

/** Group picks by season, preserving the backend's ordering within each. */
export function groupBySeason(picks) {
  const bySeason = new Map();
  for (const p of picks || []) {
    if (!p || typeof p !== "object") continue;
    const season = p.season;
    if (!bySeason.has(season)) bySeason.set(season, []);
    bySeason.get(season).push(p);
  }
  return [...bySeason.entries()].sort((a, b) => a[0] - b[0]);
}

export default function PickProjectorPanel({ leagueKey }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const qs = leagueKey
          ? `?leagueKey=${encodeURIComponent(leagueKey)}`
          : "";
        const res = await fetch(`/api/ros/pick-projections${qs}`);
        const json = await res.json().catch(() => null);
        if (!active) return;
        if (!res.ok || !json) {
          setFailed(true);
          return;
        }
        setData(json);
      } catch {
        if (active) setFailed(true);
      }
    })();
    return () => {
      active = false;
    };
  }, [leagueKey]);

  if (failed) return null;
  if (!data) return null;
  if (data.error && QUIET_ERRORS.has(data.error)) return null;

  const ownershipReason = projectionOwnershipUnavailableReason(data);
  if (ownershipReason) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }} role="status">
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Pick Projector</div>
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
          <strong>{PICK_OWNERSHIP_UNAVAILABLE_LABEL}.</strong>{" "}
          {describePickOwnershipReason(ownershipReason)} Projected slots are
          withheld rather than shown as if every team still held only its own
          picks.
        </div>
      </div>
    );
  }

  const groups = groupBySeason(data.picks);
  // No FUTURE picks is a legitimate steady state late in a rookie-draft
  // cycle. Rendering an empty table would read as breakage.
  if (!groups.length) return null;

  const unprojectable = data?.meta?.unprojectablePicks || 0;
  // Why NO pick has a slot (no rule, no simulation, unsimulable season):
  // stated once, visibly — a tooltip alone is invisible on touch.
  const leagueNoSlotText = slotForecastReasonText(
    data?.meta?.slotForecastUnavailableReason,
  );

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Pick Projector</div>
      <div
        style={{
          fontSize: "0.72rem",
          color: "var(--subtext)",
          marginBottom: 4,
        }}
      >
        Where next season&apos;s picks are projected to land, from the season
        simulation under this league&apos;s draft-order rule: the worst final
        record picks first, and a tied record goes to the lower Points For.
      </div>
      <div
        style={{ fontSize: "0.66rem", color: "var(--muted)", marginBottom: 10 }}
      >
        Projected slots only — pick <em>values</em> come from the rankings
        pipeline and are not affected by this panel. Confidence is how likely
        the team is to land within one slot of the projection. Later drafts are
        listed without a slot rather than guessed.
      </div>

      {leagueNoSlotText ? (
        <div
          role="status"
          data-testid="pick-projector-no-forecast-note"
          style={{
            fontSize: "0.72rem",
            color: "var(--subtext)",
            marginBottom: 10,
          }}
        >
          <strong>No slot forecast.</strong> {leagueNoSlotText}
        </div>
      ) : null}

      {groups.map(([season, picks]) => (
        <div key={season} style={{ marginBottom: "var(--space-md)" }}>
          <div
            style={{
              fontSize: "0.78rem",
              fontWeight: 700,
              marginBottom: 6,
              display: "flex",
              gap: 8,
              alignItems: "baseline",
            }}
          >
            <span>{season}</span>
            <span
              style={{
                fontSize: "0.66rem",
                color: "var(--muted)",
                fontWeight: 400,
              }}
            >
              {picks[0]?.seasonsOut === 1
                ? "next draft"
                : `${picks[0]?.seasonsOut} seasons out`}
            </span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                fontSize: "0.78rem",
                borderCollapse: "collapse",
              }}
            >
              <thead>
                <tr style={{ color: "var(--subtext)", fontSize: "0.7rem" }}>
                  <th style={{ textAlign: "left" }}>Projected</th>
                  <th style={{ textAlign: "left" }}>Held by</th>
                  <th style={{ textAlign: "left" }}>Originally</th>
                  <th style={{ textAlign: "center" }}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {picks.map((p, i) => {
                  const noSlot = p.projectedSlot == null;
                  const style = confidenceStyle(p.confidence);
                  const noSlotText = slotForecastReasonText(
                    p.slotForecastUnavailableReason,
                  );
                  // A pick still with its original team is the boring
                  // case; an acquired one is the reason to read this
                  // table at all, so it is called out rather than left
                  // to a name comparison by eye.
                  const acquired =
                    p.originalRosterId != null &&
                    p.ownerRosterId != null &&
                    p.originalRosterId !== p.ownerRosterId;
                  return (
                    <tr key={`${p.label}-${p.ownerRosterId}-${i}`}>
                      <td className="font-mono" style={{ fontWeight: 700 }}>
                        {p.label}
                      </td>
                      <td>{p.ownerTeam || `Team ${p.ownerRosterId}`}</td>
                      <td
                        style={{
                          color: acquired ? "var(--cyan)" : "var(--muted)",
                        }}
                      >
                        {acquired
                          ? p.originalTeam || `Team ${p.originalRosterId}`
                          : "—"}
                      </td>
                      {noSlot ? (
                        <td
                          style={{
                            textAlign: "center",
                            color: "var(--muted)",
                          }}
                          title={noSlotText || undefined}
                          data-testid="pick-projector-no-slot"
                        >
                          No slot forecast
                        </td>
                      ) : (
                        <td
                          style={{ textAlign: "center", color: style.color }}
                        >
                          {style.label}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {unprojectable > 0 ? (
        <div style={{ fontSize: "0.66rem", color: "var(--amber)" }}>
          {unprojectable} pick{unprojectable === 1 ? "" : "s"} could not be
          projected — the original team is not in the season simulation.
          Counted rather than dropped silently.
        </div>
      ) : null}
    </div>
  );
}

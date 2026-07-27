"use client";

// PickProjectorPanel — where future picks are projected to land.
//
// Backs onto /api/ros/pick-projections, which projects the rookie-draft
// order (reverse standings) from the ROS team-strength composite and
// joins it against live pick ownership. This component is the first
// caller that endpoint has ever had.
//
// Projection/context ONLY. Blended pick values come from the canonical
// pipeline (rookie-pool tethering + the multiplicative future-year
// discount) and are untouched here — the panel says where a pick is
// expected to land, never what it is worth. Mixing the two would put a
// second, unreviewed valuation next to the real one.

import { useEffect, useState } from "react";

const CONFIDENCE_STYLE = {
  high: { color: "var(--green)", label: "high" },
  medium: { color: "var(--cyan)", label: "medium" },
  low: { color: "var(--muted)", label: "low" },
};

// The backend's degraded states are 200-with-error by that router's
// convention, and both are ordinary rather than exceptional: a league
// whose team strength has not been built yet, and an unreachable
// Sleeper. Rendering an alarming failure card for either would train
// the reader to ignore the panel.
const QUIET_ERRORS = new Set(["no_snapshot", "no_teams"]);

export function confidenceStyle(confidence) {
  return CONFIDENCE_STYLE[confidence] || CONFIDENCE_STYLE.low;
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

  const groups = groupBySeason(data.picks);
  // No FUTURE picks is a legitimate steady state late in a rookie-draft
  // cycle. Rendering an empty table would read as breakage.
  if (!groups.length) return null;

  const unprojectable = data?.meta?.unprojectablePicks || 0;

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
        Where future picks are projected to land, from current roster strength.
        Draft order is reverse standings, so the weakest projected team picks
        1.01.
      </div>
      <div
        style={{ fontSize: "0.66rem", color: "var(--muted)", marginBottom: 10 }}
      >
        Projected slots only — pick <em>values</em> come from the rankings
        pipeline and are not affected by this panel. Confidence is capped by how
        far out the draft is: nothing three seasons away is better than low.
      </div>

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
                  const style = confidenceStyle(p.confidence);
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
                      <td style={{ textAlign: "center", color: style.color }}>
                        {style.label}
                      </td>
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
          projected — the originating team has no strength score. Counted rather
          than dropped silently.
        </div>
      ) : null}
    </div>
  );
}

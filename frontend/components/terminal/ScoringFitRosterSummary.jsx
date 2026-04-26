"use client";

import { useMemo } from "react";
import { useTeam } from "@/components/useTeam";
import { useDynastyData } from "@/components/useDynastyData";
import { useTerminal } from "@/components/useTerminal";
import { useSettings } from "@/components/useSettings";
import Panel from "./Panel";

/**
 * Per-roster scoring-fit summary.
 *
 * Shows the user where THEIR roster sits on the lens vs the league
 * average:
 *   - How many fit-positive IDPs they own vs the league average
 *   - Net fit-delta across their roster
 *   - Top 3 fit-positive players they own (good keep candidates)
 *   - Top 3 fit-negative players they own (sell-high candidates)
 *
 * Auto-hides when:
 *   - The Apply Scoring Fit toggle is off (lens isn't part of the
 *     user's mental model right now)
 *   - The user has no team selected
 *
 * Computed entirely client-side from data already on each row —
 * no backend call needed.
 */

const _DELTA_THRESHOLD = 1500;

export default function ScoringFitRosterSummary() {
  const { settings } = useSettings();
  const { selectedTeam } = useTeam();
  const { rows } = useDynastyData();

  const summary = useMemo(() => {
    if (!Array.isArray(rows) || !selectedTeam?.players?.length) return null;
    const owned = new Set(
      (selectedTeam.players || []).map((n) => String(n).trim().toLowerCase())
    );
    let leagueIdpTotal = 0;
    let leaguePositiveCount = 0;
    let myIdps = [];
    for (const r of rows) {
      if (r.assetClass !== "idp") continue;
      const delta = Number(r.idpScoringFitDelta);
      if (!Number.isFinite(delta)) continue;
      const conf = r.idpScoringFitConfidence;
      if (conf !== "high" && conf !== "medium") continue;
      leagueIdpTotal += 1;
      if (delta >= _DELTA_THRESHOLD) leaguePositiveCount += 1;
      if (owned.has(String(r.name || "").trim().toLowerCase())) {
        myIdps.push({
          name: r.name,
          pos: r.pos,
          delta,
          tier: r.idpScoringFitTier,
        });
      }
    }
    if (!myIdps.length) return null;

    const myPositive = myIdps.filter((p) => p.delta >= _DELTA_THRESHOLD);
    const myNegative = myIdps.filter((p) => p.delta <= -_DELTA_THRESHOLD);
    const myNetDelta = myIdps.reduce((s, p) => s + p.delta, 0);

    // League-wide rough average: total fit-positives / number of teams.
    // Used as a comparator so the user can answer "am I ahead or
    // behind on the lens within my league?".
    const leagueAvgPositive = leagueIdpTotal > 0
      ? Math.round(leaguePositiveCount / 12)  // typical 12-team league
      : 0;

    return {
      total: myIdps.length,
      myPositive,
      myNegative,
      myNetDelta,
      leagueAvgPositive,
    };
  }, [rows, selectedTeam?.players]);

  if (!settings?.applyScoringFit || !summary) return null;

  const netSign = summary.myNetDelta > 0 ? "+" : "";
  const netColor = summary.myNetDelta > 0
    ? "var(--green, #4ade80)"
    : summary.myNetDelta < 0 ? "var(--red, #f87171)" : "var(--muted)";

  return (
    <Panel
      title="Your roster — scoring fit"
      subtitle="How your IDPs grade under YOUR league's stacked scoring"
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginBottom: 10 }}>
        <div>
          <div className="muted" style={{ fontSize: "0.66rem" }}>Fit-positive owned</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "1.0rem", fontWeight: 600 }}>
            {summary.myPositive.length}
            <span className="muted" style={{ fontSize: "0.66rem", marginLeft: 6 }}>
              (league avg {summary.leagueAvgPositive})
            </span>
          </div>
        </div>
        <div>
          <div className="muted" style={{ fontSize: "0.66rem" }}>Fit-negative owned</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "1.0rem", fontWeight: 600, color: summary.myNegative.length > 0 ? "var(--red)" : "inherit" }}>
            {summary.myNegative.length}
          </div>
        </div>
        <div>
          <div className="muted" style={{ fontSize: "0.66rem" }}>Net fit-delta</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "1.0rem", fontWeight: 600, color: netColor }}>
            {netSign}{Math.round(summary.myNetDelta).toLocaleString()}
          </div>
        </div>
        <div>
          <div className="muted" style={{ fontSize: "0.66rem" }}>IDPs scored</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "1.0rem", fontWeight: 600 }}>
            {summary.total}
          </div>
        </div>
      </div>
      {summary.myPositive.length > 0 && (
        <div style={{ marginTop: 8, fontSize: "0.72rem" }}>
          <div className="muted" style={{ fontSize: "0.66rem", marginBottom: 4 }}>
            Top fit-positive on your roster (consider keeping)
          </div>
          {summary.myPositive
            .sort((a, b) => b.delta - a.delta)
            .slice(0, 3)
            .map((p) => (
              <div key={p.name} style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}>
                <span>{p.name} <span className="muted" style={{ fontSize: "0.62rem" }}>{p.pos}</span></span>
                <span style={{ fontFamily: "var(--mono, monospace)", color: "var(--green, #4ade80)", fontWeight: 600 }}>
                  +{Math.round(p.delta).toLocaleString()}
                </span>
              </div>
            ))}
        </div>
      )}
      {summary.myNegative.length > 0 && (
        <div style={{ marginTop: 8, fontSize: "0.72rem" }}>
          <div className="muted" style={{ fontSize: "0.66rem", marginBottom: 4 }}>
            Top fit-negative on your roster (consider trading)
          </div>
          {summary.myNegative
            .sort((a, b) => a.delta - b.delta)
            .slice(0, 3)
            .map((p) => (
              <div key={p.name} style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}>
                <span>{p.name} <span className="muted" style={{ fontSize: "0.62rem" }}>{p.pos}</span></span>
                <span style={{ fontFamily: "var(--mono, monospace)", color: "var(--red, #f87171)", fontWeight: 600 }}>
                  {Math.round(p.delta).toLocaleString()}
                </span>
              </div>
            ))}
        </div>
      )}
    </Panel>
  );
}

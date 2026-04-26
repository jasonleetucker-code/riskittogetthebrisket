"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useSettings, resolveScoringFitForLeague } from "@/components/useSettings";
import Panel from "./Panel";

/**
 * Drop candidates — the lowest adjusted-value players currently
 * on the user's roster.  Best-ball companion to ``Waiver wire``:
 * when adding a FA, this surfaces who to drop first.
 *
 * Unlike trade suggestions (which need consideration), drops are a
 * unilateral roster-management decision — best-ball means the user
 * adjusts their 30-man roster every week, not the lineup.
 *
 * Fit-negative IDPs (lens says league overrates the consensus
 * market) bubble to the top when the toggle is on — those are the
 * easiest drops because the user's own scoring rates them lower
 * than the market.
 */

export default function DropCandidatesPanel() {
  const { openPlayerPopup } = useApp();
  const { selectedTeam, selectedLeagueKey } = useTeam();
  const { settings } = useSettings();
  const { applyScoringFit, scoringFitWeight } = resolveScoringFitForLeague(
    settings, selectedLeagueKey
  );
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!selectedTeam?.ownerId) return;
    async function run() {
      setLoading(true);
      try {
        const body = {
          ownerId: selectedTeam.ownerId,
          applyScoringFit,
          scoringFitWeight,
          limit: 6,
        };
        if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
        const res = await fetch("/api/waiver/drops", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (res.ok && !cancelled) setData(await res.json());
      } catch {
        // silent — empty state below covers it
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [selectedTeam?.ownerId, selectedLeagueKey, applyScoringFit, scoringFitWeight]);

  const drops = data?.drops || [];

  return (
    <Panel
      title="Drop candidates"
      subtitle={
        applyScoringFit
          ? "Lowest adjusted-value players on your roster"
          : "Lowest-value players on your roster"
      }
      actions={
        drops.length > 0 ? (
          <span className="muted" style={{ fontSize: "0.68rem" }}>
            {drops.length} candidates
          </span>
        ) : null
      }
    >
      {loading && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          Loading…
        </div>
      )}
      {!loading && drops.length === 0 && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          {selectedTeam ? "No drop candidates — every rostered player has solid value." : "Select a team to see drop candidates."}
        </div>
      )}
      {drops.map((d, i) => {
        const showFitDelta = applyScoringFit
          && typeof d.fitDelta === "number"
          && d.fitDelta <= -1500;
        return (
          <div
            key={d.name}
            role="button"
            tabIndex={0}
            onClick={() => openPlayerPopup?.({ name: d.name })}
            onKeyDown={(e) => { if (e.key === "Enter") openPlayerPopup?.({ name: d.name }); }}
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr auto auto",
              gap: 8,
              alignItems: "center",
              padding: "3px 6px",
              borderRadius: 3,
              cursor: "pointer",
              fontSize: "0.76rem",
            }}
            title={d.rationale}
          >
            <span className="muted" style={{ fontSize: "0.66rem", fontFamily: "var(--mono, monospace)" }}>
              #{i + 1}
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {d.name}
              <span className="muted" style={{ fontSize: "0.62rem", marginLeft: 6 }}>
                {d.position}
              </span>
            </span>
            {showFitDelta && (
              <span
                style={{
                  fontFamily: "var(--mono, monospace)",
                  fontSize: "0.66rem",
                  color: "var(--red, #f87171)",
                  fontWeight: 600,
                }}
                title="Fit-negative — your league's scoring rates them below market"
              >
                {Math.round(d.fitDelta).toLocaleString()}
              </span>
            )}
            <span
              style={{
                fontFamily: "var(--mono, monospace)",
                fontSize: "0.74rem",
                color: "var(--muted)",
                fontWeight: 600,
              }}
            >
              {d.adjustedValue.toLocaleString()}
            </span>
          </div>
        );
      })}
    </Panel>
  );
}

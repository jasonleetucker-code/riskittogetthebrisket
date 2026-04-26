"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useSettings, resolveScoringFitForLeague } from "@/components/useSettings";
import Panel from "./Panel";

/**
 * Waiver-wire suggestions — players currently NOT on any roster
 * in the league, ranked by adjusted value (when scoring-fit on)
 * or consensus value.  Grouped by position family (DL/LB/DB
 * folded so the user sees the best DB regardless of CB/S split).
 *
 * Pre-draft window (Feb 1 - May 11) suppresses rookies — backend
 * returns ``rookies_excluded: true`` and the panel surfaces a
 * one-line note explaining why a hyped rookie isn't here yet.
 *
 * Auto-refetches when the active league or scoring-fit settings
 * change so the user doesn't have to manually re-run.
 */

const _FAMILY_ORDER = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"];

export default function WaiverSuggestionsPanel() {
  const { openPlayerPopup } = useApp();
  const { selectedLeagueKey } = useTeam();
  const { settings } = useSettings();
  const { applyScoringFit, scoringFitWeight } = resolveScoringFitForLeague(
    settings, selectedLeagueKey
  );
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        const body = {
          applyScoringFit,
          scoringFitWeight,
        };
        if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
        const res = await fetch("/api/waiver/suggestions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err.message || "fetch failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [selectedLeagueKey, applyScoringFit, scoringFitWeight]);

  const byFamily = data?.by_family || {};
  const total = data?.total || 0;
  const rookiesExcluded = !!data?.rookies_excluded;

  return (
    <Panel
      title="Waiver wire"
      subtitle={
        applyScoringFit
          ? "Top FAs ranked by your league's stacked scoring"
          : "Top FAs by consensus value"
      }
      actions={
        total > 0 ? (
          <span className="muted" style={{ fontSize: "0.68rem" }}>
            {total} candidates
          </span>
        ) : null
      }
    >
      {loading && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          Loading…
        </div>
      )}
      {error && (
        <div style={{ fontSize: "0.72rem", color: "var(--red)", padding: 8 }}>
          {error}
        </div>
      )}
      {!loading && !error && total === 0 && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          No qualifying free agents (min value 500).
        </div>
      )}
      {rookiesExcluded && (
        <div
          className="muted"
          style={{
            fontSize: "0.66rem",
            padding: "4px 8px",
            background: "rgba(34, 211, 238, 0.08)",
            borderLeft: "3px solid var(--cyan)",
            borderRadius: "2px",
            marginBottom: 8,
            lineHeight: 1.4,
          }}
        >
          Pre-draft window (Feb 1 – May 11): rookies are placeholder names
          until the actual class is drafted.  They&apos;ll re-appear May 12.
        </div>
      )}
      {!loading && !error && total > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {_FAMILY_ORDER.map((fam) => {
            const items = byFamily[fam];
            if (!items || items.length === 0) return null;
            return (
              <div key={fam}>
                <div
                  style={{
                    fontSize: "0.62rem",
                    color: "var(--cyan)",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    marginBottom: 4,
                  }}
                >
                  {fam}
                </div>
                {items.slice(0, 6).map((c) => {
                  const showFitDelta = applyScoringFit
                    && typeof c.fitDelta === "number"
                    && Number.isFinite(c.fitDelta)
                    && Math.abs(c.fitDelta) >= 750;
                  return (
                    <div
                      key={c.name}
                      role="button"
                      tabIndex={0}
                      onClick={() => openPlayerPopup?.({ name: c.name })}
                      onKeyDown={(e) => { if (e.key === "Enter") openPlayerPopup?.({ name: c.name }); }}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr auto auto",
                        gap: 8,
                        alignItems: "center",
                        padding: "3px 6px",
                        borderRadius: 3,
                        cursor: "pointer",
                        fontSize: "0.76rem",
                      }}
                      title={`${c.name} · ${c.position} · consensus ${c.consensusValue.toLocaleString()}${
                        c.adjustedValue !== c.consensusValue
                          ? ` → adjusted ${c.adjustedValue.toLocaleString()}`
                          : ""
                      }`}
                    >
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {c.name}
                        <span className="muted" style={{ fontSize: "0.62rem", marginLeft: 6 }}>
                          {c.position}
                        </span>
                        {c.isRookie && (
                          <span
                            style={{
                              fontSize: "0.58rem",
                              marginLeft: 6,
                              padding: "0 4px",
                              borderRadius: 2,
                              background: "rgba(34, 211, 238, 0.18)",
                              color: "var(--cyan)",
                              fontWeight: 600,
                            }}
                          >
                            R
                          </span>
                        )}
                      </span>
                      {showFitDelta && (
                        <span
                          style={{
                            fontFamily: "var(--mono, monospace)",
                            fontSize: "0.66rem",
                            color: c.fitDelta > 0 ? "var(--green, #4ade80)" : "var(--red, #f87171)",
                            fontWeight: 600,
                          }}
                        >
                          {c.fitDelta > 0 ? "+" : ""}{Math.round(c.fitDelta).toLocaleString()}
                        </span>
                      )}
                      <span
                        style={{
                          fontFamily: "var(--mono, monospace)",
                          fontSize: "0.74rem",
                          fontWeight: 600,
                        }}
                      >
                        {c.adjustedValue.toLocaleString()}
                      </span>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

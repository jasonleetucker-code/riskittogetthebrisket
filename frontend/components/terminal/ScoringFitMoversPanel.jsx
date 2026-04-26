"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import Panel from "./Panel";

/**
 * Scoring-fit movers — players whose ``idpScoringFitDelta`` jumped
 * (or cratered) most since the most recent captured snapshot.
 *
 * Distinct from ``MoversPanel`` which tracks rank changes from the
 * scrape pipeline; this one tracks lens-output changes.  When the
 * lens delta jumps +2400 since last snapshot, that's a "the league's
 * scoring caught something the consensus market hasn't priced in"
 * moment — different signal class than rank movement.
 *
 * Auto-hides when:
 *   - Apply Scoring Fit toggle is OFF (keep the lens off the
 *     ``/league`` hub for users who haven't opted in).
 *   - No baseline snapshot exists yet (fresh deploy, before the
 *     daily capture cron has run).
 *
 * Data source: ``GET /api/scoring-fit/movers``.
 */

function MoverRow({ entry, onClick }) {
  const change = Number(entry.change) || 0;
  const sign = change > 0 ? "+" : "";
  const color = change > 0 ? "var(--green, #4ade80)" : "var(--red, #f87171)";
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter") onClick?.(); }}
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 8,
        padding: "4px 6px",
        borderRadius: 4,
        cursor: "pointer",
      }}
      title={`${entry.name} · prior delta ${entry.prior_delta} → current ${entry.current_delta}`}
    >
      <div style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        <span style={{ fontWeight: 600, fontSize: "0.78rem" }}>{entry.name}</span>
        <span className="muted" style={{ fontSize: "0.66rem", marginLeft: 6 }}>{entry.position}</span>
      </div>
      <div style={{
        fontFamily: "var(--mono, monospace)",
        fontSize: "0.74rem",
        color,
        fontWeight: 600,
      }}>
        {sign}{Math.round(change).toLocaleString()}
      </div>
    </div>
  );
}

export default function ScoringFitMoversPanel() {
  const { openPlayerPopup } = useApp();
  const { settings } = useSettings();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const res = await fetch("/api/scoring-fit/movers", { cache: "no-store" });
        if (res.ok && !cancelled) setData(await res.json());
      } catch {
        // Silently swallow — empty state below renders correctly.
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, []);

  // Hide when the user hasn't opted into the lens — keeps the
  // /league hub clean for non-IDP-focused users.
  if (!settings?.applyScoringFit) return null;

  const risers = data?.risers || [];
  const fallers = data?.fallers || [];
  const hasBaseline = !!data?.has_baseline;
  const hasContent = hasBaseline && (risers.length || fallers.length);

  return (
    <Panel
      title="Scoring-fit movers"
      subtitle={
        hasBaseline && data?.baseline_date
          ? `Lens delta change vs ${data.baseline_date} snapshot`
          : "Awaiting baseline snapshot"
      }
    >
      {loading && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          Loading…
        </div>
      )}
      {!loading && !hasBaseline && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          The first snapshot is captured by the daily refresh.  Once a
          baseline exists this panel will surface IDPs whose lens delta
          moved most since.
        </div>
      )}
      {!loading && hasContent && (
        <div className="row" style={{ gap: 12, alignItems: "stretch" }}>
          <div style={{ flex: "1 1 220px" }}>
            <div style={{ fontSize: "0.62rem", color: "var(--green)", fontWeight: 700, textTransform: "uppercase", marginBottom: 4 }}>
              Risers — lens caught something
            </div>
            {risers.length === 0 ? (
              <div className="muted" style={{ fontSize: "0.7rem", padding: "6px 0" }}>
                No qualifying risers.
              </div>
            ) : (
              risers.map((r) => (
                <MoverRow
                  key={`r-${r.name}`}
                  entry={r}
                  onClick={() => openPlayerPopup?.({ name: r.name })}
                />
              ))
            )}
          </div>
          <div style={{ flex: "1 1 220px" }}>
            <div style={{ fontSize: "0.62rem", color: "var(--red)", fontWeight: 700, textTransform: "uppercase", marginBottom: 4 }}>
              Fallers — lens cooled on them
            </div>
            {fallers.length === 0 ? (
              <div className="muted" style={{ fontSize: "0.7rem", padding: "6px 0" }}>
                No qualifying fallers.
              </div>
            ) : (
              fallers.map((f) => (
                <MoverRow
                  key={`f-${f.name}`}
                  entry={f}
                  onClick={() => openPlayerPopup?.({ name: f.name })}
                />
              ))
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

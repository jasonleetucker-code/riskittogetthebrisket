"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useTerminal } from "@/components/useTerminal";
import { computePortfolio } from "@/lib/portfolio-insights";
import Panel from "./Panel";

const POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "IDP", "PICK"];
const AGE_ORDER = [
  { key: "rookie", label: "Rookie", hint: "≤ 22 / rookie flag" },
  { key: "young",  label: "Young",  hint: "23–24" },
  { key: "prime",  label: "Prime",  hint: "25–28" },
  { key: "vet",    label: "Vet",    hint: "29+" },
  { key: "unknown",label: "?",      hint: "age missing" },
];
const VOL_ORDER = [
  { key: "low",     label: "Low" },
  { key: "med",     label: "Med" },
  { key: "high",    label: "High" },
  { key: "unknown", label: "N/A" },
];

function formatValue(v) {
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString();
}

function formatPct(v) {
  if (!Number.isFinite(v)) return "—";
  return `${v.toFixed(v < 10 ? 1 : 0)}%`;
}

/**
 * Portfolio Summary — front-office dashboard for the signed-in roster.
 *
 * Reads the portfolio snapshot from ``computePortfolio`` and renders
 * five dense subsections:
 *   - Aggregate header (total + starter vs bench split bar)
 *   - Positional allocation (value-weighted stack)
 *   - Age mix (value-weighted segments)
 *   - Volatility exposure (value-weighted segments)
 *   - Starting XI (top 10 starters as clickable chips)
 *
 * All numbers trace back to contract fields or named derived metrics.
 * No fake data, no filler chips.
 */
export default function PortfolioSummary() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam, idpEnabled } = useTeam();
  // IDP gating: skip the IDP positional bucket (and any IDP rows in
  // the positional stack) for leagues that don't support IDP.  The
  // portfolio computation still runs globally on the contract; we
  // just don't surface an "IDP: 0" row or any stray IDP entries
  // that might have sneaked in via a shared contract.  Matches the
  // rankings-page IDP-tab gating.
  const posOrder = useMemo(
    () => (idpEnabled ? POS_ORDER : POS_ORDER.filter((p) => p !== "IDP")),
    [idpEnabled],
  );
  const { history, loading: historyLoading } = useRankHistory({ days: 30 });

  // Server-side portfolio (aggregates + byPosition + byAge +
  // volExposure + counters) when the /api/terminal call is
  // authenticated and resolves a team.  Anonymous / un-resolved
  // cases fall through to local ``computePortfolio`` which walks
  // the same backend-stamped row values but does the grouping in
  // the browser.
  const { portfolio: serverPortfolio } = useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  const localPortfolio = useMemo(
    () => computePortfolio({ rows, selectedTeam, rawData, history }),
    [rows, selectedTeam, rawData, history],
  );

  // Merge: prefer server-computed sub-sections when present; fall
  // back to the local computation for starter/bench split and pick
  // totals, which the server doesn't compute.  Every field the UI
  // below reads (byPosition, byAge, volExposure, totalValue, etc.)
  // comes from whichever source provided it first.
  const portfolio = useMemo(() => {
    if (!localPortfolio) return null;
    if (!serverPortfolio) return localPortfolio;
    return {
      ...localPortfolio,
      // Server fields override locals where both exist.
      totalValue: serverPortfolio.totalValue ?? localPortfolio.totalValue,
      byPosition: serverPortfolio.byPosition || localPortfolio.byPosition,
      byAge: serverPortfolio.byAge || localPortfolio.byAge,
      volExposure: serverPortfolio.volExposure || localPortfolio.volExposure,
      medianAge: serverPortfolio.medianAge ?? localPortfolio.medianAge,
    };
  }, [serverPortfolio, localPortfolio]);

  if (!selectedTeam) {
    return (
      <Panel title="Portfolio" subtitle="Positional allocation" className="panel--portfolio">
        <div className="portfolio-empty">Pick a team to see allocation.</div>
      </Panel>
    );
  }

  if (!portfolio) {
    return (
      <Panel title="Portfolio" subtitle="Positional allocation" className="panel--portfolio">
        <div className="portfolio-empty">
          {historyLoading ? "Loading portfolio…" : "No roster data resolved."}
        </div>
      </Panel>
    );
  }

  const {
    totalValue,
    starterValue,
    benchValue,
    starterCount,
    benchCount,
    starters,
    pickCount,
    pickValue,
    byPosition,
    byAge,
    volExposure,
    unresolved,
    coverage,
  } = portfolio;

  // Split bar is lineup-only: picks aren't eligible for start/bench
  // slots, so they'd otherwise create a phantom gap in the bar.
  // Picks still appear in Total Value above and in the PICK column
  // of the positional stack below.
  const lineupValue = starterValue + benchValue;
  const starterPct = lineupValue ? (starterValue / lineupValue) * 100 : 0;

  return (
    <Panel
      title="Portfolio"
      subtitle="Value, allocation, age + volatility"
      className="panel--portfolio"
    >
      {/* ── Aggregate header ── */}
      <div className="portfolio-agg">
        <div className="portfolio-agg-stat">
          <span className="portfolio-agg-label">Total Value</span>
          <span className="portfolio-agg-value">{formatValue(totalValue)}</span>
          {coverage < 1 && unresolved.length > 0 && (
            <span className="portfolio-agg-hint">
              {unresolved.length} unresolved
            </span>
          )}
        </div>
        <div className="portfolio-split" aria-label="Starter vs bench value">
          <div className="portfolio-split-bar">
            <span
              className="portfolio-split-starter"
              style={{ width: `${starterPct}%` }}
              aria-hidden="true"
            />
          </div>
          <div className="portfolio-split-legend">
            <span>
              <strong>Starters</strong>{" "}
              {formatValue(starterValue)} · {formatPct(starterPct)} · {starterCount}
            </span>
            <span>
              <strong>Bench</strong>{" "}
              {formatValue(benchValue)} · {formatPct(100 - starterPct)} · {benchCount}
            </span>
            {pickCount > 0 && (
              <span>
                <strong>Picks</strong>{" "}
                {formatValue(pickValue)} · {pickCount}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Positional allocation ── */}
      <section className="portfolio-section">
        <h3 className="portfolio-section-title">Positional allocation</h3>
        <div className="portfolio-stack">
          {posOrder.map((pos) => {
            const entry = byPosition[pos];
            if (!entry || entry.count === 0) return null;
            return (
              <div key={pos} className="portfolio-stack-row">
                <span className="portfolio-stack-label">{pos}</span>
                <div className="portfolio-stack-bar">
                  <span
                    className="portfolio-stack-fill"
                    style={{ width: `${Math.min(entry.pct, 100)}%` }}
                  />
                </div>
                <span className="portfolio-stack-value">
                  {formatValue(entry.value)}
                  <span className="portfolio-stack-meta">
                    {" "}· {entry.count} · {formatPct(entry.pct)}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Age mix (value-weighted) ── */}
      {(() => {
        // When every resolved player is in the "unknown" bucket the
        // section adds nothing but a flat purple bar with a confused
        // "? 100%" legend.  That happens when the contract hasn't
        // stamped birthdates (e.g. a fresh league sync, or a Sleeper
        // outage) — surface that state honestly instead of pretending
        // the data is meaningful.
        const unknownEntry = byAge?.unknown;
        const totalAgeCount = AGE_ORDER.reduce(
          (acc, a) => acc + (byAge?.[a.key]?.count || 0),
          0,
        );
        const allUnknown =
          totalAgeCount > 0 &&
          unknownEntry &&
          unknownEntry.count === totalAgeCount;
        return (
          <section className="portfolio-section">
            <h3 className="portfolio-section-title">Age mix (by value)</h3>
            {allUnknown ? (
              <div className="portfolio-empty-inline">
                Age data unavailable for this roster.
              </div>
            ) : (
              <>
                <div className="portfolio-seg-bar" role="img" aria-label="Age distribution">
                  {AGE_ORDER.map((a) => {
                    const entry = byAge[a.key];
                    if (!entry || entry.pct === 0) return null;
                    return (
                      <span
                        key={a.key}
                        className={`portfolio-seg portfolio-seg--age-${a.key}`}
                        style={{ flex: entry.pct }}
                        title={`${a.label}: ${formatPct(entry.pct)} · ${entry.count} player${entry.count === 1 ? "" : "s"}`}
                      />
                    );
                  })}
                </div>
                <div className="portfolio-seg-legend">
                  {AGE_ORDER.map((a) => {
                    const entry = byAge[a.key];
                    if (!entry || entry.count === 0) return null;
                    return (
                      <span key={a.key} className="portfolio-seg-legend-item">
                        <span className={`portfolio-seg-swatch portfolio-seg--age-${a.key}`} aria-hidden="true" />
                        <span className="portfolio-seg-legend-label">{a.label}</span>
                        <span className="portfolio-seg-legend-value">{formatPct(entry.pct)}</span>
                      </span>
                    );
                  })}
                </div>
              </>
            )}
          </section>
        );
      })()}

      {/* ── Volatility exposure ── */}
      <section className="portfolio-section">
        <h3 className="portfolio-section-title">Volatility exposure (by value)</h3>
        <div className="portfolio-seg-bar" role="img" aria-label="Volatility distribution">
          {VOL_ORDER.map((v) => {
            const entry = volExposure[v.key];
            if (!entry || entry.pct === 0) return null;
            return (
              <span
                key={v.key}
                className={`portfolio-seg portfolio-seg--vol-${v.key}`}
                style={{ flex: entry.pct }}
                title={`${v.label}: ${formatPct(entry.pct)} · ${entry.count} player${entry.count === 1 ? "" : "s"}`}
              />
            );
          })}
        </div>
        <div className="portfolio-seg-legend">
          {VOL_ORDER.map((v) => {
            const entry = volExposure[v.key];
            if (!entry || entry.count === 0) return null;
            return (
              <span key={v.key} className="portfolio-seg-legend-item">
                <span className={`portfolio-seg-swatch portfolio-seg--vol-${v.key}`} aria-hidden="true" />
                <span className="portfolio-seg-legend-label">{v.label}</span>
                <span className="portfolio-seg-legend-value">{formatPct(entry.pct)}</span>
              </span>
            );
          })}
        </div>
      </section>

      {/* ── Starters list ── */}
      {starters.length > 0 && (
        <section className="portfolio-section">
          <h3 className="portfolio-section-title">
            Starters <span className="portfolio-section-hint">click to open</span>
          </h3>
          <ul className="portfolio-starters">
            {starters.slice(0, 12).map((p) => (
              <li key={p.name}>
                <button
                  type="button"
                  className="portfolio-starter"
                  onClick={() => openPlayerPopup?.(p.name)}
                  title={`${p.name} — ${formatValue(p.value)}`}
                >
                  <span className="portfolio-starter-pos">{p.pos}</span>
                  <span className="portfolio-starter-name">{p.name}</span>
                  <span className="portfolio-starter-value">{formatValue(p.value)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Panel>
  );
}

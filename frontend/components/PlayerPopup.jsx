"use client";

import { useCallback, useEffect, useMemo } from "react";
import { getPlayerEdge } from "@/lib/trade-logic";
import { resolvedRank } from "@/lib/dynasty-data";

/**
 * Player detail popup — multi-source breakdown, value diagnostics, edge signal.
 * Triggered by clicking a player name anywhere in the app.
 *
 * Props:
 *   row       — Player row object from buildRows() (null to hide popup)
 *   siteKeys  — Array of site key strings from dynasty data
 *   onClose   — Callback to close the popup
 *   onAddToTrade — Optional callback to add player to trade builder
 */
export default function PlayerPopup({ row, siteKeys = [], onClose, onAddToTrade }) {
  // Close on Escape
  useEffect(() => {
    if (!row) return;
    function onKey(e) { if (e.key === "Escape") onClose?.(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [row, onClose]);

  const edge = useMemo(() => (row ? getPlayerEdge(row) : null), [row]);

  const siteDetails = useMemo(() => {
    if (!row?.canonicalSites) return [];
    const maxVal = Math.max(1, ...Object.values(row.canonicalSites).map(Number).filter(Number.isFinite));
    return (siteKeys.length > 0 ? siteKeys : Object.keys(row.canonicalSites))
      .map((key) => {
        const val = Number(row.canonicalSites[key]);
        if (!Number.isFinite(val) || val <= 0) return null;
        return { key, value: val, pct: (val / maxVal) * 100 };
      })
      .filter(Boolean)
      .sort((a, b) => b.value - a.value);
  }, [row, siteKeys]);

  // Consensus narrative based on coefficient of variation
  const consensusText = useMemo(() => {
    if (siteDetails.length <= 1) return siteDetails.length === 1 ? "Only 1 source — speculative" : "";
    const vals = siteDetails.map((s) => s.value);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, v) => a + Math.pow(v - mean, 2), 0) / vals.length;
    const cv = mean > 0 ? Math.sqrt(variance) / mean : 0;
    if (cv < 0.15) return `Strong consensus (CV ${(cv * 100).toFixed(0)}%) — sources agree closely`;
    if (cv < 0.30) return `Moderate agreement (CV ${(cv * 100).toFixed(0)}%) — some spread between sources`;
    return `Sources disagree significantly (CV ${(cv * 100).toFixed(0)}%) — high volatility player`;
  }, [siteDetails]);

  if (!row) return null;

  const rank = resolvedRank(row);
  const values = row.values || {};

  return (
    <div className="picker-overlay" onClick={onClose} style={{ zIndex: 1100 }}>
      <div
        className="picker-sheet"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 520, width: "95vw" }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{row.name}</h2>
            <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
              <span className="badge">{row.pos}</span>
              {row.raw?.team && <span className="muted" style={{ fontSize: "0.76rem" }}>{row.raw.team}</span>}
              {row.raw?.rookie && <span className="badge" style={{ color: "var(--cyan)", borderColor: "var(--cyan)" }}>ROOKIE</span>}
              {rank < Infinity && (
                <span className="muted" style={{ fontSize: "0.72rem" }}>Rank #{rank}</span>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {onAddToTrade && (
              <button className="button" style={{ fontSize: "0.72rem", padding: "4px 8px" }}
                onClick={() => { onAddToTrade(row); onClose?.(); }}>
                Add to Trade
              </button>
            )}
            <button className="button" onClick={onClose} style={{ fontSize: "0.82rem", padding: "4px 10px" }}>
              &times;
            </button>
          </div>
        </div>

        {/* Primary value */}
        <div style={{ display: "flex", gap: 20, marginTop: 14, flexWrap: "wrap" }}>
          <div>
            <div className="label">Our Value</div>
            <div className="value" style={{ fontSize: "1.4rem" }}>{Math.round(values.full || 0).toLocaleString()}</div>
          </div>
          {values.raw > 0 && values.raw !== values.full && (
            <div>
              <div className="label">Raw</div>
              <div className="value">{Math.round(values.raw).toLocaleString()}</div>
            </div>
          )}
          {values.scoring > 0 && values.scoring !== values.raw && (
            <div>
              <div className="label">Scoring</div>
              <div className="value">{Math.round(values.scoring).toLocaleString()}</div>
            </div>
          )}
          {values.scarcity > 0 && values.scarcity !== values.scoring && (
            <div>
              <div className="label">Scarcity</div>
              <div className="value">{Math.round(values.scarcity).toLocaleString()}</div>
            </div>
          )}
          {values.full !== values.raw && (
            <div>
              <div className="label">Delta</div>
              <div className="value" style={{ color: values.full > values.raw ? "var(--green)" : "var(--red)" }}>
                {values.full > values.raw ? "+" : ""}{Math.round(values.full - values.raw).toLocaleString()}
              </div>
            </div>
          )}
        </div>

        {/* Edge signal */}
        {edge?.signal && (
          <div style={{ marginTop: 10, padding: "6px 10px", borderRadius: 6,
            background: edge.signal === "BUY" ? "rgba(52,211,153,0.1)" : "rgba(248,113,113,0.1)" }}>
            <span style={{ fontWeight: 700, fontSize: "0.82rem",
              color: edge.signal === "BUY" ? "var(--green)" : "var(--red)" }}>
              {edge.signal === "BUY" ? "Buy Low" : "Sell High"}
            </span>
            <span className="muted" style={{ marginLeft: 8, fontSize: "0.76rem" }}>
              {edge.edgePct}% edge vs. external sources ({edge.sources.join(", ")})
            </span>
          </div>
        )}

        {/* Source breakdown bars */}
        {siteDetails.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div className="label" style={{ marginBottom: 6 }}>Source Breakdown</div>
            {siteDetails.map((s) => (
              <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <div style={{ minWidth: 90, fontSize: "0.72rem" }} className="muted">{s.key}</div>
                <div style={{ flex: 1, height: 14, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{
                    width: `${Math.min(100, s.pct)}%`, height: "100%", borderRadius: 3,
                    background: s.pct >= 90 ? "var(--green)" : s.pct >= 50 ? "var(--cyan)" : "var(--red)",
                    transition: "width 0.3s",
                  }} />
                </div>
                <div style={{ minWidth: 56, textAlign: "right", fontSize: "0.76rem", fontWeight: 600 }}>
                  {Math.round(s.value).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Consensus narrative */}
        {consensusText && (
          <div className="muted" style={{ marginTop: 10, fontSize: "0.74rem", fontStyle: "italic" }}>
            {consensusText}
          </div>
        )}

        {/* Source count + site count */}
        <div className="muted" style={{ marginTop: 8, fontSize: "0.7rem", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          {row.siteCount > 0 && <span>{row.siteCount} source{row.siteCount !== 1 ? "s" : ""} contributing</span>}
          {row.canonicalTierId && <span> · Tier {row.canonicalTierId}</span>}
        </div>
      </div>
    </div>
  );
}

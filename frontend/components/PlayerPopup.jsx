"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getPlayerEdge } from "@/lib/trade-logic";
import { resolvedRank } from "@/lib/dynasty-data";

/**
 * Build the ordered value-chain stages from a player row.
 *
 * Pipeline order (from src/api/data_contract.py Phase 3 → 4c):
 *   1. Blended Hill value — trimmed mean-median across per-source
 *      Hill-curve values → stamped as ``rankDerivedValueUncalibrated``.
 *   2. IDP calibration pass (family_scale × bucket multiplier) —
 *      IDP rows only; offense rows skip this stage.  Output is the
 *      final ``rankDerivedValue``.
 *
 * The prior volatility-compression stage was removed along with the
 * monotonicity cap; see docs/architecture/live-value-pipeline-trace.md.
 *
 * Only stages with a meaningful delta are emitted so offense rows
 * don't render zero-op "IDP calibration ×1.00" rows.
 */
function computeValueChain(row) {
  if (!row) return [];

  const stages = [];

  // Stage 1 — blended value (trimmed mean-median across Hill-curve
  // values from every contributing source).
  const blended = Number(row.rankDerivedValueUncalibrated) || null;
  if (blended !== null && blended > 0) {
    stages.push({
      key: "blend",
      label: "Blended value",
      description:
        "Trimmed mean-median across per-source Hill-curve values",
      value: Math.round(blended),
      delta: null,
    });
  }

  // Stage 2 — IDP calibration (family_scale × bucket multiplier).
  // Offense rows lack these fields and skip this stage.
  const bucket =
    typeof row.idpCalibrationMultiplier === "number"
      ? row.idpCalibrationMultiplier
      : null;
  const family =
    typeof row.idpFamilyScale === "number" ? row.idpFamilyScale : null;
  const posRank =
    typeof row.idpCalibrationPositionRank === "number"
      ? row.idpCalibrationPositionRank
      : null;
  const finalValue = Number(row.rankDerivedValue) || 0;
  if (family !== null && bucket !== null && finalValue > 0) {
    const combined = family * bucket;
    const prior = stages.length ? stages[stages.length - 1].value : null;
    const delta = prior !== null ? Math.round(finalValue) - prior : null;
    // Skip if the calibration is a clean no-op AND there's no delta.
    if (!(Math.abs(combined - 1.0) < 1e-9 && (delta === null || delta === 0))) {
      const posLabel =
        posRank && row.pos ? ` (${row.pos}${posRank})` : "";
      stages.push({
        key: "idp-calibration",
        label: `IDP calibration: ×${combined.toFixed(2)}`,
        description: `Family scale ×${family.toFixed(2)} × bucket multiplier ×${bucket.toFixed(2)}${posLabel}`,
        value: Math.round(finalValue),
        delta,
      });
    }
  }

  return stages;
}

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
  const [chainOpen, setChainOpen] = useState(false);

  // Close on Escape
  useEffect(() => {
    if (!row) return;
    function onKey(e) { if (e.key === "Escape") onClose?.(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [row, onClose]);

  // Reset the chain panel when switching players — the new row's
  // transforms are different, so starting collapsed keeps the
  // popup compact for casual lookups.
  useEffect(() => {
    setChainOpen(false);
  }, [row?.name]);

  const edge = useMemo(() => (row ? getPlayerEdge(row) : null), [row]);
  const valueChain = useMemo(() => computeValueChain(row), [row]);

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
          {values.full !== values.raw && (
            <div>
              <div className="label">Delta</div>
              <div className="value" style={{ color: values.full > values.raw ? "var(--green)" : "var(--red)" }}>
                {values.full > values.raw ? "+" : ""}{Math.round(values.full - values.raw).toLocaleString()}
              </div>
            </div>
          )}
        </div>

        {/* Value chain — how we arrived at Our Value */}
        {valueChain.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              onClick={() => setChainOpen((v) => !v)}
              style={{
                background: "transparent",
                border: "1px dashed var(--border-bright)",
                color: "var(--cyan)",
                padding: "4px 10px",
                borderRadius: 6,
                fontSize: "0.72rem",
                cursor: "pointer",
                fontFamily: "var(--font)",
                width: "100%",
                textAlign: "left",
              }}
              title={
                chainOpen
                  ? "Hide the stage-by-stage value derivation"
                  : "See how the blended value + volatility + calibration produced the final number"
              }
            >
              {chainOpen ? "▼" : "▶"} Value chain — how we got {Math.round(values.full || 0).toLocaleString()}
              {!chainOpen && (
                <span className="muted" style={{ marginLeft: 8, fontSize: "0.68rem" }}>
                  {valueChain.length} stage{valueChain.length !== 1 ? "s" : ""}
                </span>
              )}
            </button>
            {chainOpen && (
              <div
                style={{
                  marginTop: 6,
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: "8px 10px",
                  background: "rgba(79, 38, 131, 0.12)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                {valueChain.map((stage, i) => (
                  <div
                    key={stage.key}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      paddingBottom: i === valueChain.length - 1 ? 0 : 6,
                      borderBottom:
                        i === valueChain.length - 1
                          ? "none"
                          : "1px dashed var(--border)",
                    }}
                  >
                    <div
                      style={{
                        minWidth: 22,
                        textAlign: "center",
                        color: "var(--cyan)",
                        fontWeight: 700,
                        fontSize: "0.72rem",
                      }}
                    >
                      {i + 1}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: "0.78rem", fontWeight: 600 }}>
                        {stage.label}
                      </div>
                      <div
                        className="muted"
                        style={{ fontSize: "0.68rem", marginTop: 2 }}
                      >
                        {stage.description}
                      </div>
                    </div>
                    <div
                      style={{
                        minWidth: 72,
                        textAlign: "right",
                        fontFamily: "var(--mono)",
                        fontSize: "0.78rem",
                        fontWeight: 700,
                      }}
                    >
                      {stage.value.toLocaleString()}
                      {stage.delta !== null && stage.delta !== 0 && (
                        <div
                          style={{
                            fontSize: "0.66rem",
                            fontWeight: 500,
                            color:
                              stage.delta > 0
                                ? "var(--green)"
                                : "var(--red)",
                          }}
                        >
                          {stage.delta > 0 ? "+" : ""}
                          {stage.delta.toLocaleString()}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

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

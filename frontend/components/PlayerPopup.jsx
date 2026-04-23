"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getPlayerEdge } from "@/lib/trade-logic";
import { resolvedRank, RANKING_SOURCES } from "@/lib/dynasty-data";
import PlayerRankHistoryChart from "@/components/PlayerRankHistoryChart";
import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";
import { useUserState } from "@/components/useUserState";

/**
 * Build the ordered value-chain stages from a player row.
 *
 * Pipeline order (Final Framework live chain,
 * src/api/data_contract.py Phase 3):
 *   1. Anchor value — IDPTC's percentile-Hill value for this player,
 *      or the subgroup-only fallback when IDPTC doesn't rank them.
 *   2. Subgroup adjustment — trimmed mean-median of non-anchor source
 *      values, shrunk by α into the anchor baseline: center =
 *      anchor + α·(subgroup − anchor).  Only emitted when both
 *      anchor and subgroup contribute.
 *   3. MAD volatility penalty — center − λ·MAD (players only; picks
 *      skip this stage).
 *   4. Combined output → ``rankDerivedValue``.
 *
 * (The former IDP calibration post-pass — family_scale × bucket
 * multiplier — was retired alongside the rest of the calibration
 * system, so the chain no longer has a Stage 5.)
 */
function computeValueChain(row) {
  if (!row) return [];

  const stages = [];

  // Stage 1 — anchor baseline.  IDPTC's percentile-Hill value.
  const anchor = Number(row.anchorValue) || null;
  const subgroupBlend = Number(row.subgroupBlendValue) || null;
  const subgroupDelta =
    typeof row.subgroupDelta === "number" ? row.subgroupDelta : null;
  const alpha =
    typeof row.alphaShrinkage === "number" ? row.alphaShrinkage : null;

  if (anchor !== null && anchor > 0) {
    stages.push({
      key: "anchor",
      label: "Anchor value",
      description:
        "IDPTC percentile-Hill — the universal offense+IDP baseline",
      value: Math.round(anchor),
      delta: null,
    });
  } else if (subgroupBlend !== null && subgroupBlend > 0) {
    // Player only has subgroup coverage (no anchor) — surface the
    // subgroup blend as the effective baseline.
    stages.push({
      key: "subgroup-only",
      label: "Subgroup baseline",
      description:
        "No anchor coverage — trimmed mean-median of subgroup sources",
      value: Math.round(subgroupBlend),
      delta: null,
    });
  }

  // Stage 2 — α-shrunk subgroup adjustment (only when both anchor and
  // subgroup are present and the adjustment is non-zero).
  if (
    anchor !== null &&
    anchor > 0 &&
    subgroupBlend !== null &&
    subgroupDelta !== null &&
    alpha !== null &&
    Math.round(alpha * subgroupDelta) !== 0
  ) {
    const adjusted = Math.round(anchor + alpha * subgroupDelta);
    const prior = stages.length ? stages[stages.length - 1].value : null;
    stages.push({
      key: "subgroup",
      label: `Subgroup adjustment ×${alpha.toFixed(2)}`,
      description:
        `Subgroup blend ${Math.round(subgroupBlend)} − anchor ` +
        `${Math.round(anchor)} = Δ${subgroupDelta >= 0 ? "+" : ""}` +
        `${Math.round(subgroupDelta)}; shrunk by α=${alpha.toFixed(2)}`,
      value: adjusted,
      delta: prior !== null ? adjusted - prior : null,
    });
  }

  // λ·MAD penalty retired 2026-04-20.  ``sourceSpread`` is rendered
  // below the chain as a pure transparency metric.
  const blended = Number(row.rankDerivedValue) || null;
  if (blended !== null && blended > 0 && stages.length === 0) {
    // Offense rows (no anchor/subgroup stamps) — surface the final
    // blended value as a single "Blended value" chain row.
    stages.push({
      key: "blend",
      label: "Blended value",
      description:
        "Count-aware mean-median over every source that ranked this " +
        "player (value-based sources vote with their raw values; " +
        "rank-only sources go through the Hill curve).",
      value: Math.round(blended),
      delta: null,
    });
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

  // Close on Escape + lock body scroll while open.
  //
  // Body-scroll lock: when the popup is open we set ``overflow:
  // hidden`` on ``document.body`` so a user scrolling inside the
  // popup doesn't accidentally drive the page behind.  On unmount
  // (or when ``row`` flips back to null) we restore whatever was
  // there before — reading the prior value rather than hard-coding
  // "" avoids clobbering a parent component that might have set
  // ``overflow: scroll`` for its own reasons.  Combined with
  // ``overscroll-behavior: contain`` on the sheet in CSS, this
  // fully isolates scrolling inside the popup.
  useEffect(() => {
    if (!row) return;
    function onKey(e) { if (e.key === "Escape") onClose?.(); }
    document.addEventListener("keydown", onKey);
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = priorOverflow;
    };
  }, [row, onClose]);

  // Reset the chain panel when switching players — the new row's
  // transforms are different, so starting collapsed keeps the
  // popup compact for casual lookups.
  useEffect(() => {
    setChainOpen(false);
  }, [row?.name]);

  const edge = useMemo(() => (row ? getPlayerEdge(row) : null), [row]);
  const valueChain = useMemo(() => computeValueChain(row), [row]);

  // Injury impact lookup from the server-side signals block.
  // Only populated for roster players today — non-roster players
  // won't have impact data, and the chip simply doesn't render.
  const { selectedTeam } = useTeam();
  const { signals: serverSignals } = useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });
  const injury = useMemo(() => {
    const name = String(row?.name || "").toLowerCase();
    if (!name) return null;
    const hit = (serverSignals || []).find(
      (s) => s?.name && String(s.name).toLowerCase() === name,
    );
    if (!hit?.injuryImpact) return null;
    return { impact: hit.injuryImpact, adjustedValue: hit.injuryAdjustedValue };
  }, [serverSignals, row?.name]);

  // Watchlist toggle — wires the ⭐ button in the popup header to
  // useUserState.toggleWatchlist.  ``serverBacked`` drives the
  // tooltip so users know whether the state syncs across devices.
  const { state: userState, toggleWatchlist, serverBacked: userStateServerBacked } = useUserState();
  const onWatchlist = useMemo(() => {
    const name = String(row?.name || "").toLowerCase();
    if (!name) return false;
    const list = userState?.watchlist || [];
    return list.some((x) => String(x).toLowerCase() === name);
  }, [userState?.watchlist, row?.name]);

  const siteDetails = useMemo(() => {
    if (!row) return [];
    // Prefer the backend's 9,999-scale ``valueContribution`` stamp —
    // the same normalized vote each source casts into the blend, and
    // the same number rendered in the rankings row chips.  Reading
    // ``canonicalSites`` here (the previous behaviour) mixed value
    // sources' raw native scale with rank-signal sources' synthetic
    // rank encoding (``_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - rank *
    // 100``), so IDP expert boards like DLF IDP / FBG IDP were either
    // dwarfed to invisible bars or dropped entirely by the
    // normalized-vs-maxVal math — producing the classic "Only 1 source
    // — speculative" line on a player that actually had 4 sources
    // contributing.  Using ``sourceRankMeta[key].valueContribution``
    // keeps the popup in lockstep with the rankings table.
    const meta = row.sourceRankMeta || {};
    const canonicalSites = row.canonicalSites || {};
    const sourceByKey = Object.fromEntries(
      RANKING_SOURCES.map((s) => [s.key, s]),
    );
    const candidateKeys = Array.from(
      new Set([
        ...(siteKeys.length > 0 ? siteKeys : []),
        ...Object.keys(meta),
        ...Object.keys(canonicalSites),
      ]),
    );
    const rows = candidateKeys
      .map((key) => {
        const src = sourceByKey[key];
        const label = src?.columnLabel || src?.displayName || key;
        const contribution = Number(meta[key]?.valueContribution);
        if (Number.isFinite(contribution) && contribution > 0) {
          return { key, label, value: contribution };
        }
        // Legacy payloads may not carry ``valueContribution`` yet.
        // Fall back to ``canonicalSites`` only for value-based sources
        // — their raw slot is a monotonic value scale.  Rank-signal
        // sources skip this path because their canonicalSites entry is
        // a synthetic rank encoding, not a renderable value.
        if (src?.isRankSignal) return null;
        const raw = Number(canonicalSites[key]);
        if (Number.isFinite(raw) && raw > 0) {
          return { key, label, value: raw };
        }
        return null;
      })
      .filter(Boolean);
    const maxVal = Math.max(1, ...rows.map((r) => r.value));
    return rows
      .map((r) => ({ ...r, pct: (r.value / maxVal) * 100 }))
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
        className="picker-sheet picker-sheet--scrollable"
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
            <button
              type="button"
              className={`button player-popup-watchlist${onWatchlist ? " is-active" : ""}`}
              onClick={() => toggleWatchlist(row.name)}
              aria-pressed={onWatchlist}
              title={
                onWatchlist
                  ? userStateServerBacked
                    ? "Remove from watchlist (synced)"
                    : "Remove from watchlist"
                  : userStateServerBacked
                  ? "Add to watchlist (synced across devices)"
                  : "Add to watchlist (local)"
              }
            >
              {onWatchlist ? "★" : "☆"}
            </button>
            {onAddToTrade && (
              <button
                className="button player-popup-action"
                onClick={() => { onAddToTrade(row); onClose?.(); }}
                aria-label={`Add ${row.name} to trade`}
              >
                Add to Trade
              </button>
            )}
            <button
              className="button player-popup-close"
              onClick={onClose}
              aria-label="Close player details"
              title="Close"
            >
              &times;
            </button>
          </div>
        </div>

        {/* Primary value — ``Our Value`` is the live blended
            ``rankDerivedValue`` with no post-blend adjustments.  The
            IDP calibration post-pass was retired, so there are no
            longer two values to compare (the "Raw / Delta" pair from
            the original legacy pipeline was already removed earlier
            for a separate reason — it subtracted a legacy composite
            from the Hill blend, which produced misleading four-digit
            "discounts" on every IDP row). */}
        <div style={{ display: "flex", gap: 20, marginTop: 14, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <div className="label">Our Value</div>
            <div className="value" style={{ fontSize: "1.4rem" }}>{Math.round(values.full || 0).toLocaleString()}</div>
          </div>
          {injury && injury.impact?.appliedDiscountPct > 0 && (
            <div>
              <div className="label" style={{ color: "var(--red)" }}>
                Adjusted (injury −{Number(injury.impact.appliedDiscountPct).toFixed(
                  injury.impact.appliedDiscountPct < 1 ? 2 : 1,
                )}%)
              </div>
              <div className="value" style={{ fontSize: "1.4rem", color: "var(--red)" }}>
                {Number.isFinite(Number(injury.adjustedValue))
                  ? Number(injury.adjustedValue).toLocaleString()
                  : "—"}
              </div>
            </div>
          )}
          {injury && injury.impact?.offseasonSuppressed && (
            <div
              className="muted"
              style={{ fontSize: "0.72rem", fontStyle: "italic", paddingBottom: 6 }}
              title={`Headline: ${injury.impact.headline}`}
            >
              Injury news · offseason (value unchanged)
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
                  background: "rgba(79, 33, 133, 0.12)",
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
              {edge.signal === "BUY"
                ? `Consensus ranks ${edge.rankGap} spots higher than KTC — market is cheap`
                : `KTC ranks ${edge.rankGap} spots higher than consensus — market overvalues`}
              {edge.edgePct > 0 && <> · ~{edge.edgePct}% value gap</>}
            </span>
          </div>
        )}

        {/* 180-day rank-history mini-chart */}
        <div style={{ marginTop: 14 }}>
          <PlayerRankHistoryChart row={row} />
        </div>

        {/* Source breakdown bars */}
        {siteDetails.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div className="label" style={{ marginBottom: 6 }}>Source Breakdown</div>
            {siteDetails.map((s) => (
              <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <div
                  style={{ minWidth: 90, fontSize: "0.72rem" }}
                  className="muted"
                  title={s.key}
                >
                  {s.label}
                </div>
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

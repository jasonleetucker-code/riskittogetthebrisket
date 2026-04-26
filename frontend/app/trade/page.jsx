"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import {
  RANKING_SOURCES,
  SOURCE_VENDOR_LABELS,
  vendorForSource,
} from "@/lib/dynasty-data";
import {
  VALUE_MODES,
  STORAGE_KEY,
  RECENT_KEY,
  verdictFromGap,
  colorFromGap,
  verdictBarPosition,
  adjustedSideTotals,
  multiAdjustedSideTotals,
  tradeGapAdjusted,
  sideTotal,
  effectiveValue,
  displayValue,
  getPlayerEdge,
  findBalancers,
  parsePickToken,
  resolvePickRow,
  meterVerdict,
  percentageGap,
  multiTeamAnalysis,
  createSide,
  serializeWorkspaceMulti,
  deserializeWorkspaceMulti,
  valueAdjustmentFromSideArrays,
  defaultDestination,
  computeSideFlows,
  computeSideFlowAssets,
  SIDE_LABELS,
  MAX_SIDES,
  MIN_SIDES,
} from "@/lib/trade-logic";
import { useSettings } from "@/components/useSettings";
import TradeDeltaHistogram from "@/components/graphs/TradeDeltaHistogram";
import MultiTradeFlow from "@/components/graphs/MultiTradeFlow";
import { useApp } from "@/components/AppShell";
import { posBadgeClass } from "@/lib/display-helpers";
import {
  buildShareUrl,
  parseShareParam,
  SHARE_PARAM,
} from "@/lib/trade-share";
import { useTradeSimulator } from "@/components/useTradeSimulator";
import { useTeam } from "@/components/useTeam";
import { MonteCarloButton, ValueBandBadge, PlayerImage } from "@/components/ui";
import ResilientSection from "@/components/ResilientSection";

const ROSTER_KEY = "next_trade_roster_v1";
const TEAM_KEY = "next_trade_team_v1";
const SUGG_TYPES = [
  { key: "sellHigh", label: "Sell High" },
  { key: "buyLow", label: "Buy Low" },
  { key: "consolidation", label: "Consolidation" },
  { key: "positionalUpgrades", label: "Upgrades" },
];

function fairnessColor(f) {
  if (f === "even") return "var(--green)";
  if (f === "lean") return "var(--cyan)";
  return "var(--red)";
}

// Compact "Recommended right now" rail.  Surfaces the top
// suggestion from each populated category so the user sees
// actionable trade ideas at-a-glance — instead of having to scroll
// down + click ``Get Suggestions`` first.  Click a card to populate
// the trade builder with the give/get pair.
const SUGGESTION_RAIL_LABELS = {
  sellHigh: { label: "Sell High", color: "var(--cyan)", hint: "These pieces have peaked — convert before the market cools." },
  buyLow: { label: "Buy Low", color: "var(--green)", hint: "Undervalued by the consensus right now." },
  consolidation: { label: "Consolidation", color: "var(--amber)", hint: "Trade pile-of-assets for a single anchor." },
  positionalUpgrades: { label: "Upgrade", color: "var(--purple)", hint: "Direct positional swaps that net you value." },
};

function ProactiveSuggestionsRail({ suggestions, onApply }) {
  // For each category, take the top suggestion (already sorted by
  // the engine).  Skip categories with zero results.
  const cards = [];
  for (const [key, meta] of Object.entries(SUGGESTION_RAIL_LABELS)) {
    const list = suggestions[key] || [];
    if (list.length === 0) continue;
    cards.push({ key, meta, top: list[0], remaining: list.length - 1 });
  }
  if (cards.length === 0) return null;
  return (
    <div
      className="card"
      style={{
        marginBottom: 10,
        padding: "10px 12px",
        background: "rgba(255, 199, 4, 0.04)",
        border: "1px solid rgba(255, 199, 4, 0.18)",
      }}
    >
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
        Recommended right now · top idea per category
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 8,
        }}
      >
        {cards.map((c) => (
          <button
            key={c.key}
            type="button"
            className="button-reset"
            onClick={() => onApply(c.top)}
            title={c.meta.hint}
            style={{
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "8px 10px",
              background: "rgba(8, 19, 44, 0.55)",
              cursor: "pointer",
              textAlign: "left",
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: "0.62rem", color: c.meta.color, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                {c.meta.label}
              </span>
              {c.remaining > 0 && (
                <span style={{ fontSize: "0.58rem", color: "var(--subtext)" }}>
                  +{c.remaining} more
                </span>
              )}
            </div>
            <div style={{ fontSize: "0.78rem", lineHeight: 1.3 }}>
              <span style={{ color: "var(--subtext)" }}>Give:</span>{" "}
              <span style={{ fontWeight: 600 }}>
                {(c.top.give || []).map((p) => p.name).join(" + ") || "—"}
              </span>
            </div>
            <div style={{ fontSize: "0.78rem", lineHeight: 1.3 }}>
              <span style={{ color: "var(--subtext)" }}>Get:</span>{" "}
              <span style={{ fontWeight: 600, color: c.meta.color }}>
                {(c.top.receive || []).map((p) => p.name).join(" + ") || "—"}
              </span>
            </div>
            <div style={{ fontSize: "0.62rem", color: "var(--subtext)", marginTop: 2 }}>
              Tap to load into the trade builder ↓
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function fairnessLabel(f) {
  if (f === "even") return "Even value";
  if (f === "lean") return "Slight lean";
  return "Stretch";
}

function confidenceBadge(c) {
  if (c === "high") return { label: "High consensus", bg: "rgba(52,211,153,0.15)", border: "rgba(52,211,153,0.4)", color: "var(--green)" };
  if (c === "medium") return { label: "Moderate consensus", bg: "rgba(255, 199, 4,0.12)", border: "rgba(255, 199, 4,0.35)", color: "var(--cyan)" };
  return { label: "Low consensus", bg: "rgba(153,166,200,0.1)", border: "var(--border)", color: "var(--muted)" };
}

function edgeBadge(edge) {
  if (!edge) return null;
  if (edge === "market_discount") return { text: "Buy Low", bg: "rgba(52,211,153,0.15)", color: "var(--green)" };
  if (edge === "market_premium") return { text: "Sell High", bg: "rgba(248,113,113,0.15)", color: "var(--red)" };
  if (edge === "high_dispersion") return { text: "Sources Disagree", bg: "rgba(251,191,36,0.15)", color: "#fbbf24" };
  return null;
}

/* ── Trade Meter Component ───────────────────────────────────────────── */

function TradeMeter({ sides, sideTotals, flows, valueMode, settings }) {
  const sideCount = sides.length;

  if (sideCount === 2) {
    return <TradeMeterTwoTeam sides={sides} sideTotals={sideTotals} />;
  }
  return <TradeMeterMultiTeam sides={sides} sideTotals={sideTotals} flows={flows} />;
}

function TradeMeterTwoTeam({ sides, sideTotals }) {
  const pwA = sideTotals[0]?.adjusted || 0;
  const pwB = sideTotals[1]?.adjusted || 0;
  const gap = pwA - pwB;
  const absGap = Math.abs(gap);
  const pctGap = percentageGap(pwA, pwB);
  const verdict = meterVerdict(absGap);
  const maxVal = Math.max(pwA, pwB);
  const total = pwA + pwB;

  // Fill percentages for the bar
  const shareA = total > 0 ? (pwA / total) * 100 : 50;
  const shareB = total > 0 ? (pwB / total) * 100 : 50;

  // Winner label
  let winnerText = "Even";
  if (pctGap >= 3) {
    winnerText = gap > 0
      ? `Side A wins by ${pctGap}%`
      : `Side B wins by ${pctGap}%`;
  }

  return (
    <div className="trade-meter">
      {/* Value comparison */}
      <div className="trade-meter-values">
        <span className="trade-meter-side-val">{Math.round(pwA).toLocaleString()}</span>
        <span className="trade-meter-vs">vs</span>
        <span className="trade-meter-side-val">{Math.round(pwB).toLocaleString()}</span>
        <span className="trade-meter-gap">Gap: {Math.round(absGap).toLocaleString()}</span>
      </div>

      {/* Horizontal balance bar */}
      <div className="trade-meter-bar">
        <div
          className="trade-meter-fill trade-meter-fill-a"
          style={{ width: `${shareA}%` }}
        />
        <div
          className="trade-meter-fill trade-meter-fill-b"
          style={{ width: `${shareB}%` }}
        />
        <div className="trade-meter-center" />
      </div>
      <div className="trade-meter-bar-labels">
        <span className="muted" style={{ fontSize: "0.66rem" }}>Side A</span>
        <span className="muted" style={{ fontSize: "0.66rem" }}>Side B</span>
      </div>

      {/* Verdict badge + percentage */}
      <div className="trade-meter-bottom">
        <span className={`trade-meter-verdict trade-meter-verdict-${verdict.level}`}>
          {verdict.label}
        </span>
        <span className="trade-meter-pct">{winnerText}</span>
      </div>

      {/* Monte Carlo simulator — renders nothing when flag off, a
          button when flag on and trade has assets, or a "flag off"
          pill when backend returns 503.  Wrapped in ResilientSection
          so an MC-panel crash doesn't take down the trade meter. */}
      <ResilientSection name="Monte Carlo panel">
        <MonteCarloButton sides={sides} />
      </ResilientSection>
    </div>
  );
}

function TradeMeterMultiTeam({ sides, sideTotals, flows }) {
  // In 3+-team trades the fairness story is per-side NET (received −
  // given), not the sum-of-totals share used by ``multiTeamAnalysis``.
  // A side that gives away a 9000-value QB and receives a 9000-value
  // WR is even on flow, even though the grand total counted both.
  // The bar below shows each side's NET on a zero-centered axis so
  // getters (positive) and over-payers (negative) read at a glance.
  const flowList = Array.isArray(flows) && flows.length === sides.length
    ? flows
    : sides.map(() => ({ given: 0, received: 0, net: 0 }));
  const nets = flowList.map((f) => f.net);
  const absMax = Math.max(350, ...nets.map((n) => Math.abs(n)));

  // Overall verdict: worst-offender absolute net.  Reuses the
  // 350/900/1800 thresholds in ``meterVerdict`` so the label text
  // matches the 2-team bar.
  const worst = Math.max(...nets.map((n) => Math.abs(n)));
  const verdict = meterVerdict(worst);

  const fmtSigned = (n) => {
    const sign = n > 0 ? "+" : n < 0 ? "−" : "";
    return `${sign}${Math.round(Math.abs(n)).toLocaleString()}`;
  };
  const netColor = (n) => {
    if (Math.abs(n) < 350) return "var(--muted)";
    return n > 0 ? "var(--green)" : "var(--red)";
  };
  const netTag = (n) => {
    if (Math.abs(n) < 350) return "Even";
    if (n > 0) return "Getting value";
    return "Losing value";
  };

  return (
    <div className="trade-meter">
      {/* Per-side NET row */}
      <div className="trade-meter-multi-values">
        {sides.map((s, i) => {
          const flow = flowList[i] || { given: 0, received: 0, net: 0 };
          return (
            <div key={s.id} className="trade-meter-multi-val">
              <span className="label">Side {s.label}</span>
              <span
                className="trade-meter-side-val"
                style={{ color: netColor(flow.net) }}
              >
                {fmtSigned(flow.net)}
              </span>
              <span className="muted" style={{ fontSize: "0.64rem" }}>
                {netTag(flow.net)}
              </span>
              <span className="muted" style={{ fontSize: "0.6rem" }}>
                Give {Math.round(flow.given).toLocaleString()} · Get {Math.round(flow.received).toLocaleString()}
              </span>
            </div>
          );
        })}
      </div>

      {/* Zero-centered NET bar per side.  Each side gets 1/N of the
           horizontal axis; within its slot the fill grows left-from-
           center (red) or right-from-center (green) proportional to
           |net| / absMax. */}
      <div style={{ display: "flex", gap: 4, margin: "8px 0 4px" }}>
        {sides.map((s, i) => {
          const net = nets[i] || 0;
          const pct = absMax > 0 ? Math.min(100, (Math.abs(net) / absMax) * 100) : 0;
          const isPos = net > 0;
          const isEven = Math.abs(net) < 350;
          const fillColor = isEven
            ? "var(--muted)"
            : isPos
              ? "var(--green)"
              : "var(--red)";
          return (
            <div
              key={s.id}
              style={{
                flex: 1,
                position: "relative",
                height: 14,
                background: "rgba(153,166,200,0.08)",
                borderRadius: 6,
                overflow: "hidden",
              }}
              title={`Side ${s.label}: ${fmtSigned(net)}`}
            >
              {/* Center marker */}
              <div
                style={{
                  position: "absolute",
                  left: "50%",
                  top: 0,
                  bottom: 0,
                  width: 1,
                  background: "var(--border)",
                }}
              />
              {/* Fill */}
              <div
                style={{
                  position: "absolute",
                  top: 2,
                  bottom: 2,
                  width: `${pct / 2}%`,
                  background: fillColor,
                  opacity: 0.75,
                  borderRadius: 4,
                  ...(isPos
                    ? { left: "50%" }
                    : { right: "50%" }),
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="trade-meter-bar-labels">
        {sides.map((s, i) => (
          <span
            key={s.id}
            className="muted"
            style={{
              fontSize: "0.62rem",
              flex: 1,
              textAlign: "center",
              color: netColor(nets[i] || 0),
            }}
          >
            {s.label}: {fmtSigned(nets[i] || 0)}
          </span>
        ))}
      </div>

      {/* Overall verdict */}
      <div className="trade-meter-bottom">
        <span className={`trade-meter-verdict trade-meter-verdict-${verdict.level}`}>
          {verdict.label}
        </span>
        <span className="trade-meter-pct" style={{ marginLeft: 8 }}>
          Worst gap: {fmtSigned(worst)}
        </span>
      </div>
    </div>
  );
}

/* ── Per-source Trade Breakdown ──────────────────────────────────────── */

/**
 * Render a per-vendor winner table below the main trade meter.
 *
 * Sources that share a vendor (e.g. dlfSf + dlfIdp + dlfRookieSf +
 * dlfRookieIdp all belong to DLF) are consolidated into one row so
 * rookie-for-veteran trades don't artificially split the DLF opinion
 * across its sub-boards.  For each vendor + side, we sum every
 * covered sub-source's ``sourceRankMeta[subKey].valueContribution``
 * — the per-source Hill-curve output on the canonical 0-9999 scale —
 * which puts every vendor on the same axis as KTC instead of the
 * pre-cap synthetic 999,XXX values used internally for sort ordering.
 *
 * Margin is rendered as a percent of the winner's total so a 5%
 * margin on DLF is directly comparable to a 5% margin on KTC even
 * though their total scales aren't identical.
 */
function TradeSourceBreakdown({ sides, settings }) {
  const [mobileExpanded, setMobileExpanded] = useState(false);
  // Mirror the CSS breakpoint so aria-expanded reflects what's
  // actually rendered: on desktop the body is always visible, on
  // mobile it follows mobileExpanded. State-driven so SSR renders a
  // consistent "desktop = expanded" view and the first client paint
  // after hydration flips narrow viewports to the collapsed state
  // without a hydration mismatch.
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mq = window.matchMedia("(max-width: 768px)");
    const update = () => setIsMobile(mq.matches);
    update();
    // iOS Safari < 14 only exposes addListener/removeListener on
    // MediaQueryList; modern browsers support the standard
    // EventTarget API.  Prefer the modern API and fall back for
    // older WebViews that would otherwise throw.
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", update);
      return () => mq.removeEventListener("change", update);
    }
    mq.addListener(update);
    return () => mq.removeListener(update);
  }, []);
  const effectiveExpanded = isMobile ? mobileExpanded : true;
  const rows = useMemo(() => {
    const assetsBySide = sides.map((s) => s.assets || []);
    const hasAny = assetsBySide.some((a) => a.length > 0);
    if (!hasAny) return [];

    // Walk RANKING_SOURCES in its canonical order, grouping each
    // source under its vendor.  Vendors appear in the order their
    // first sub-source is registered.
    const vendorOrder = [];
    const vendorSubs = new Map();
    for (const src of RANKING_SOURCES) {
      const vendor = vendorForSource(src.key);
      if (!vendorSubs.has(vendor)) {
        vendorSubs.set(vendor, []);
        vendorOrder.push(vendor);
      }
      vendorSubs.get(vendor).push(src);
    }

    return vendorOrder
      .map((vendor) => {
        const subs = vendorSubs.get(vendor);
        // Picks are included only for KTC — it's the canonical pick-
        // valuation board.  Every other vendor leaves picks uncovered
        // and would skew the piece-count math if we counted them.
        const includePicks = vendor === "ktc";
        // Sub-board priority rule: main boards win over rookie-
        // specialty boards.  Once a rookie is promoted onto a
        // vendor's main SF/IDP board (typically post-NFL-draft), the
        // main board reflects that vendor's current opinion and the
        // rookie board is a historical pre-draft artifact.  So for
        // each vendor + player we look at non-rookie sub-boards
        // first; only if none of them cover the player do we fall
        // back to the vendor's rookie sub-boards.  In either tier,
        // covered sub-boards are averaged together — unbiased in the
        // rare case of multi-board overlap within the same tier, and
        // equivalent to "pick whichever one covered" in the common
        // case where only one sub-board covers a given player.
        const mainSubs = subs.filter((s) => !s.needsRookieTranslation);
        const rookieSubs = subs.filter((s) => s.needsRookieTranslation);
        // Per-source value resolution.
        //
        // For KTC specifically, the V13 Value Adjustment formula and
        // its empirical suppression thresholds (V13_SUPPRESS_RAW_DIFF,
        // V13_SUPPRESS_SAME_SIDE_RAW_DIFF) were calibrated against
        // KTC's raw 0-9999 piece values.  Feeding the formula the
        // canonical Hill-blended ``valueContribution`` instead would
        // mis-fire VA — sometimes suppressing a real VA, sometimes
        // inventing one — and the per-source KTC row would disagree
        // with what keeptradecut.com displays for the same trade.
        // We therefore use the raw KTC value from
        // ``row.canonicalSites['ktc']`` as the formula input for the
        // KTC vendor row.
        //
        // For every other vendor we keep the Hill-normalized
        // ``valueContribution``: rank-only sources don't have a raw
        // native value, and cross-market rank sources stash a
        // synthetic 100,000+ rank-encoded number in ``canonicalSites``
        // that would break the V13 formula's 0-9999-scaled ratios.
        const useRawNative = vendor === "ktc";
        const sourceValueForRow = (row, sub) => {
          if (useRawNative) {
            const native = Number(row.canonicalSites?.[sub.key]);
            if (Number.isFinite(native) && native > 0) return native;
          }
          const vc = Number(row.sourceRankMeta?.[sub.key]?.valueContribution);
          return Number.isFinite(vc) && vc > 0 ? vc : 0;
        };
        const averageCovered = (row, sourceList) => {
          let sum = 0;
          let covered = 0;
          for (const sub of sourceList) {
            const v = sourceValueForRow(row, sub);
            if (v > 0) {
              sum += v;
              covered += 1;
            }
          }
          return covered > 0 ? sum / covered : 0;
        };
        const sideValues = assetsBySide.map((assets) =>
          assets.map((row) => {
            if (!includePicks && row.pos === "PICK") return 0;
            const mainAvg = averageCovered(row, mainSubs);
            if (mainAvg > 0) return mainAvg;
            return averageCovered(row, rookieSubs);
          }),
        );
        const rawTotals = sideValues.map((vs) =>
          vs.reduce((sum, v) => sum + v, 0),
        );
        const coverage = sideValues.map((vs) => vs.filter((v) => v > 0).length);
        // Skip vendors that touch zero pieces across the whole trade.
        if (coverage.reduce((a, b) => a + b, 0) === 0) return null;

        const adjustments = valueAdjustmentFromSideArrays(sideValues);
        const adjustedTotals = rawTotals.map((t, i) => t + (adjustments[i] || 0));

        // Winner + margin.  For 2-team trades the margin is |A − B|.
        // For N ≥ 3 the winner is whoever's adjusted total is biggest.
        let winnerIdx = 0;
        for (let i = 1; i < adjustedTotals.length; i++) {
          if (adjustedTotals[i] > adjustedTotals[winnerIdx]) winnerIdx = i;
        }
        const runnerUp = adjustedTotals
          .filter((_, i) => i !== winnerIdx)
          .reduce((max, v) => Math.max(max, v), 0);
        const rawMargin = adjustedTotals[winnerIdx] - runnerUp;
        const winnerTotal = adjustedTotals[winnerIdx];
        const marginPct =
          winnerTotal > 0 ? (rawMargin / winnerTotal) * 100 : 0;
        const tied = rawMargin < 1;

        // Display label: use SOURCE_VENDOR_LABELS for multi-board
        // vendors (DLF, Flock, FBG, DraftSharks, FantasyPros);
        // single-board vendors fall back to their sub-source's
        // columnLabel/displayName (ktc → "KTC", dynastyDaddySf →
        // "DD", etc.).
        const primary = subs[0];
        const label =
          SOURCE_VENDOR_LABELS[vendor] ||
          primary.columnLabel ||
          primary.displayName ||
          vendor;
        const displayName = SOURCE_VENDOR_LABELS[vendor]
          ? subs.map((s) => s.displayName || s.key).join(" + ")
          : primary.displayName || primary.key;

        return {
          key: vendor,
          label,
          displayName,
          rawTotals,
          adjustments,
          adjustedTotals,
          coverage,
          winnerIdx: tied ? null : winnerIdx,
          winnerLabel: tied ? "Even" : sides[winnerIdx]?.label || "?",
          marginPct,
        };
      })
      .filter(Boolean);
  }, [sides, settings]);

  if (rows.length === 0) {
    return null;
  }

  const sideLabels = sides.map((s) => s.label);

  return (
    <div
      className={`card source-breakdown-card${mobileExpanded ? " is-expanded" : ""}`}
      style={{ marginTop: 14 }}
    >
      <button
        type="button"
        className="source-breakdown-header"
        aria-expanded={effectiveExpanded}
        aria-controls="source-breakdown-body"
        tabIndex={isMobile ? 0 : -1}
        onClick={() => {
          if (isMobile) setMobileExpanded((v) => !v);
        }}
      >
        <span className="source-breakdown-header-text">
          <span
            className="source-breakdown-title"
            style={{ margin: 0, fontSize: "0.88rem", fontWeight: 700 }}
          >
            Per-source winner
          </span>
          <span className="muted source-breakdown-subtitle" style={{ fontSize: "0.72rem" }}>
            VA-adjusted totals on the 0-9999 value scale, summed per vendor. Sub-boards (e.g. DLF SF + DLF RK) roll up into one row; margin shows winner's edge as a percent.
          </span>
        </span>
        <span className="source-breakdown-chevron" aria-hidden="true">
          {mobileExpanded ? "−" : "+"}
        </span>
      </button>
      <div
        id="source-breakdown-body"
        className="source-breakdown-body"
        style={{ overflowX: "auto" }}
      >
        <table className="source-breakdown-table">
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Source</th>
              {sideLabels.map((lbl, i) => (
                <th key={`h-${i}`} style={{ textAlign: "right" }}>
                  Side {lbl}
                </th>
              ))}
              <th style={{ textAlign: "center" }}>Winner</th>
              <th style={{ textAlign: "right" }}>Margin</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td
                  style={{ textAlign: "left", whiteSpace: "nowrap" }}
                  title={row.displayName}
                >
                  {row.label}
                </td>
                {row.adjustedTotals.map((total, i) => {
                  const hasAdj = (row.adjustments[i] || 0) > 0;
                  return (
                    <td
                      key={`v-${row.key}-${i}`}
                      style={{
                        textAlign: "right",
                        fontFamily: "var(--mono)",
                        opacity: row.coverage[i] === 0 ? 0.35 : 1,
                        fontWeight: row.winnerIdx === i ? 700 : 400,
                      }}
                      title={
                        hasAdj
                          ? `raw ${Math.round(row.rawTotals[i]).toLocaleString()} + VA ${Math.round(row.adjustments[i]).toLocaleString()}`
                          : `raw ${Math.round(row.rawTotals[i]).toLocaleString()}`
                      }
                    >
                      {Math.round(total).toLocaleString()}
                      {hasAdj && (
                        <span
                          style={{
                            color: "var(--cyan)",
                            fontSize: "0.68rem",
                            marginLeft: 4,
                          }}
                        >
                          +VA
                        </span>
                      )}
                    </td>
                  );
                })}
                <td
                  style={{
                    textAlign: "center",
                    fontWeight: 700,
                    color:
                      row.winnerIdx === null
                        ? "var(--muted)"
                        : row.winnerIdx === 0
                          ? "var(--green)"
                          : row.winnerIdx === 1
                            ? "var(--red)"
                            : "var(--cyan)",
                  }}
                >
                  {row.winnerIdx === null ? "Even" : `Side ${row.winnerLabel}`}
                </td>
                <td
                  style={{
                    textAlign: "right",
                    fontFamily: "var(--mono)",
                    color: row.winnerIdx === null ? "var(--muted)" : "var(--text)",
                  }}
                >
                  {row.winnerIdx === null
                    ? "—"
                    : `${row.marginPct.toFixed(1)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Main Trade Page ─────────────────────────────────────────────────── */

export default function TradePage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup, registerAddToTrade } = useApp();
  const [valueMode, setValueMode] = useState("full");
  const [pickerSortCol, setPickerSortCol] = useState("rank");
  const [pickerSortAsc, setPickerSortAsc] = useState(true);

  // Multi-team state: array of { id, label, assets }
  const [sides, setSides] = useState([
    createSide(0),
    createSide(1),
  ]);
  const [activeSide, setActiveSide] = useState(0); // index into sides
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerFilter, setPickerFilter] = useState("all");
  const [recentNames, setRecentNames] = useState([]);
  const [hydrated, setHydrated] = useState(false);
  const pickerInputRef = useRef(null);

  // Suggestions state
  const [rosterInput, setRosterInput] = useState("");
  const [suggestions, setSuggestions] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState(null);
  const [suggestionTab, setSuggestionTab] = useState("sellHigh");

  // Sleeper team selection state
  const [selectedTeamIdx, setSelectedTeamIdx] = useState(-1);
  const [leagueRosters, setLeagueRosters] = useState(null);

  // KTC import panel state — toggles an inline url-paste row above
  // the trade sides.  ``ktcImportStatus`` holds the post-submit
  // summary message (success count + any unresolved ids).
  const [ktcImportOpen, setKtcImportOpen] = useState(false);
  const [ktcImportUrl, setKtcImportUrl] = useState("");
  const [ktcImportBusy, setKtcImportBusy] = useState(false);
  const [ktcImportError, setKtcImportError] = useState("");
  const [ktcImportStatus, setKtcImportStatus] = useState("");

  // Share + simulator state.
  const [shareStatus, setShareStatus] = useState("");
  const [shareHydrated, setShareHydrated] = useState(false);
  const { simulate: simulateTrade, result: simResult, loading: simLoading, error: simError, reset: resetSim } = useTradeSimulator();
  // useTeam is already league-aware: ``selectedTeam`` resolves
  // against the active league, ``idpEnabled`` comes from the
  // league config, ``leagueMismatch`` flags the data-not-ready
  // state.  We use all three below to render the right picker
  // options, auto-attach the right league to trade suggestions,
  // and show a clear "data not ready" banner when needed.
  const {
    selectedTeam,
    idpEnabled,
    leagueMismatch,
    selectedLeagueKey,
  } = useTeam();

  // Extract Sleeper teams from dynasty data
  const sleeperTeams = useMemo(() => {
    const teams = rawData?.sleeper?.teams;
    return Array.isArray(teams) && teams.length > 0 ? teams : null;
  }, [rawData]);

  const rowByName = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.name, r));
    return m;
  }, [rows]);

  // Lowercased-name → row map for the Sleeper pick resolver; matches
  // the shape ``resolvePickRow`` expects.  Built alongside rowByName
  // so both are available when we need to translate a Sleeper roster
  // string like "2026 1.12 (own)" back into a rankings row.
  const rowByLowerName = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.name.toLowerCase(), r));
    return m;
  }, [rows]);
  const pickAliases = rawData?.pickAliases || null;

  /**
   * Resolve a Sleeper team's roster into a Set of rankings-row NAMES.
   * Players are looked up verbatim (same display-name space); picks
   * route through ``resolvePickRow`` so Sleeper's "2026 1.12 (own)"
   * ends up pointing at the rankings "2026 Pick 1.12" row.  Only
   * assets the rankings actually know about land in the set, which
   * is exactly what the balancer filter needs (unknown names would
   * filter nothing useful).
   */
  const teamRosterNames = useCallback(
    (team) => {
      const names = new Set();
      if (!team) return names;
      for (const p of team.players || []) {
        if (!p) continue;
        if (rowByName.has(p)) names.add(p);
      }
      for (const pickLabel of team.picks || []) {
        const row = resolvePickRow(pickLabel, rowByLowerName, pickAliases);
        if (row) names.add(row.name);
      }
      return names;
    },
    [rowByName, rowByLowerName, pickAliases],
  );

  /**
   * Figure out which Sleeper team most likely owns a given side's
   * assets pre-trade.  Scores each team by count of matched assets
   * (players + picks, resolved through ``teamRosterNames``); returns
   * the team with the most matches, or null if no team matches any.
   *
   * Used to filter balancer suggestions so "add these to balance"
   * only shows players ALREADY on the team sitting on that side of
   * the trade.  A mixed side (assets spanning multiple rosters)
   * still resolves to the best single-team match, which is usually
   * the right answer in practice — trades happen against one
   * partner, not a pool.
   */
  const inferTeamForSide = useCallback(
    (side) => {
      if (!sleeperTeams || !side?.assets?.length) return null;
      const assetNames = new Set(side.assets.map((a) => a.name));
      let bestTeam = null;
      let bestCount = 0;
      for (const team of sleeperTeams) {
        const roster = teamRosterNames(team);
        let count = 0;
        for (const n of assetNames) {
          if (roster.has(n)) count += 1;
        }
        if (count > bestCount) {
          bestCount = count;
          bestTeam = team;
        }
      }
      return bestCount > 0 ? bestTeam : null;
    },
    [sleeperTeams, teamRosterNames],
  );

  // Hydrate roster input, team selection, and recent names from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(ROSTER_KEY);
      if (saved) setRosterInput(saved);
    } catch { /* ignore */ }
    try {
      const savedTeam = localStorage.getItem(TEAM_KEY);
      if (savedTeam !== null) setSelectedTeamIdx(Number(savedTeam));
    } catch { /* ignore */ }
    try {
      const rawRecent = localStorage.getItem(RECENT_KEY);
      if (rawRecent) {
        const parsed = JSON.parse(rawRecent);
        if (Array.isArray(parsed)) setRecentNames(parsed.filter((x) => typeof x === "string").slice(0, 20));
      }
    } catch { /* ignore */ }
  }, []);

  // Reset the picker filter to "all" if the user's on an IDP filter
  // and switches to a non-IDP league.  Mirrors the rankings-page
  // guard so the same IDP filter doesn't silently render empty.
  useEffect(() => {
    if (!idpEnabled && pickerFilter === "idp") {
      setPickerFilter("all");
    }
  }, [idpEnabled, pickerFilter]);

  // Hydrate trade workspace from localStorage (with migration)
  useEffect(() => {
    if (!rows.length || hydrated) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        const restored = deserializeWorkspaceMulti(parsed, rowByName);
        if (restored) {
          const nextMode = String(restored.valueMode || "full");
          if (VALUE_MODES.some((m) => m.key === nextMode)) setValueMode(nextMode);
          setActiveSide(restored.activeSide);
          setSides(restored.sides);
        }
      }
    } catch { /* ignore */ } finally { setHydrated(true); }
  }, [rows, hydrated, rowByName]);

  // Persist trade workspace to localStorage
  useEffect(() => {
    if (!hydrated) return;
    const payload = serializeWorkspaceMulti(sides, valueMode, activeSide);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [hydrated, valueMode, activeSide, sides]);

  // ── Share-URL decoder ──────────────────────────────────────────────
  // When the page loads with ``?share=<base64url>`` in the URL, decode
  // the payload and replace the first N sides with its contents.  We
  // wait for rows to load + localStorage hydration to finish so the
  // decoded trade doesn't flash-then-disappear when the later effect
  // commits the stored workspace.  Running once per page load is
  // enforced via ``shareHydrated`` — the user can still /clear or edit
  // the trade after, and we won't re-override from the URL.
  useEffect(() => {
    if (!hydrated || shareHydrated) return;
    if (!rows.length) return;
    if (typeof window === "undefined") return;
    const state = parseShareParam(window.location.search);
    if (!state || !state.sides?.length) {
      setShareHydrated(true);
      return;
    }
    try {
      const neededSides = Math.max(2, state.sides.length);
      const ensureSides = (prev) => {
        let next = prev;
        while (next.length < neededSides) next = [...next, createSide(next.length)];
        return next;
      };
      setSides((prev) => {
        const base = ensureSides(prev);
        return base.map((side, i) => {
          const incoming = state.sides[i];
          if (!incoming) return { ...side, assets: [], destinations: {} };
          const resolved = [];
          const seen = new Set();
          for (const name of incoming.players || []) {
            // Direct rowByName lookup catches every player and any
            // pick that happens to be in canonical form
            // ("2026 Pick 1.04").
            let row = rowByName.get(name);
            if (!row) {
              // Pick fallback: trade history items round-trip through
              // share URLs using the SLEEPER format ("2026 1.04 (from
              // Team X)" or "2027 Mid 1st (own)"), which doesn't
              // match the canonical rowByName key.  Re-use the same
              // ``resolvePickRow`` walker league-analysis uses so
              // imported trades from /trades correctly hydrate picks.
              if (parsePickToken(name)) {
                row = resolvePickRow(name, rowByLowerName, pickAliases);
              }
            }
            if (!row || seen.has(row.name)) continue;
            seen.add(row.name);
            resolved.push(row);
          }
          const nextDestinations = {};
          if (base.length > 2) {
            for (const row of resolved) {
              nextDestinations[row.name] = defaultDestination(i, base.length);
            }
          }
          return { ...side, assets: resolved, destinations: nextDestinations };
        });
      });
      setShareStatus("Loaded shared trade from link.");
    } catch {
      setShareStatus("Share link was malformed — ignored.");
    } finally {
      setShareHydrated(true);
    }
  }, [hydrated, shareHydrated, rows, rowByName]);

  useEffect(() => {
    if (pickerOpen && pickerInputRef.current) pickerInputRef.current.focus();
  }, [pickerOpen]);

  // ── Computed totals for all sides ────────────────────────────────────
  // Both 2-team and N-team trades use the KTC-style Value Adjustment.
  // For N ≥ 3, each side's VA is computed against the merged opposition
  // (every other side's assets flattened) — see
  // ``computeMultiSideAdjustments`` in trade-logic.js.
  const sideTotals = useMemo(() => {
    if (sides.length === 2) {
      const [a, b] = adjustedSideTotals(sides[0].assets, sides[1].assets, valueMode, settings);
      return [a, b];
    }
    if (sides.length > 2) {
      return multiAdjustedSideTotals(sides.map((s) => s.assets), valueMode, settings);
    }
    return sides.map((s) => {
      const raw = sideTotal(s.assets, valueMode, settings);
      return { raw, adjustment: 0, adjusted: raw };
    });
  }, [sides, valueMode, settings]);

  // Per-side flow totals: given / received / net.  In 2-team trades
  // the destinations map is ignored (assets implicitly go to the other
  // side).  In 3+-team trades each asset's destination drives the NET
  // flow, which is what the multi-team fairness bar renders.
  const sideFlows = useMemo(
    () => computeSideFlows(sides, valueMode, settings),
    [sides, valueMode, settings],
  );

  // Per-side incoming / outgoing asset lists.  This is the
  // "who's getting what" view — for each side we know exactly which
  // assets (and from whom) are arriving.  Rendered as a "Receiving"
  // section in 3+-team mode so the user doesn't have to mentally
  // reverse-lookup destinations across three separate side cards.
  const sideFlowAssets = useMemo(
    () => computeSideFlowAssets(sides),
    [sides],
  );

  // Which side is the user's own roster?  Derived by counting how
  // many of each side's current assets match the user's selected
  // Sleeper team.  Falls back to ``-1`` when there's no team
  // selected, no matches on either side, or the data isn't ready.
  // Used to label the matching side card with a "Your team" pill so
  // the user always knows which side is "I'm giving" vs. "I'm
  // receiving" — fixes the audit's U-2-style "team affordance
  // disappears once the tray scrolls" finding.
  const mySideIdx = useMemo(() => {
    if (!selectedTeam) return -1;
    const myRoster = teamRosterNames(selectedTeam);
    if (!myRoster.size) return -1;
    let bestIdx = -1;
    let bestHits = 0;
    sides.forEach((s, i) => {
      let hits = 0;
      for (const a of s.assets || []) {
        if (myRoster.has(a.name)) hits += 1;
      }
      if (hits > bestHits) {
        bestHits = hits;
        bestIdx = i;
      }
    });
    return bestHits > 0 ? bestIdx : -1;
  }, [sides, selectedTeam, teamRosterNames]);

  // Legacy 2-team gap computations (for sticky tray + 2-team balancers)
  const pwTotalA = sideTotals[0]?.adjusted || 0;
  const pwTotalB = sideTotals[1]?.adjusted || 0;
  const linTotalA = sideTotals[0]?.raw || 0;
  const linTotalB = sideTotals[1]?.raw || 0;
  const pwGap = pwTotalA - pwTotalB;
  const pctGap = Math.max(pwTotalA, pwTotalB) > 0 ? Math.round(Math.abs(pwGap) / Math.max(pwTotalA, pwTotalB) * 100) : 0;

  // Balancing suggestions (2-team mode only).
  //
  // Filter the candidate pool to the roster of whichever Sleeper team
  // owns the assets ALREADY on the behind side.  If the trade is
  // between Jason and team X, and Jason is behind, the suggestions
  // should come from Jason's roster — he's the one who'd add more
  // to his side.  Falls back to the full ranked pool when no team
  // match is found (manual-entry workflows, mixed assets, no Sleeper
  // data).  Also emits the inferred team name so the UI can label
  // "Add from [team]:" instead of a generic "consider adding".
  const balancers = useMemo(() => {
    if (sides.length !== 2) return { list: [], teamName: null };
    if (Math.abs(pwGap) < 350) return { list: [], teamName: null };
    const allInTrade = new Set(sides.flatMap((s) => s.assets.map((a) => a.name)));
    // Behind side = the one whose total is LOWER.
    const behindSideIdx = pwGap > 0 ? 1 : 0;
    const behindSide = sides[behindSideIdx];
    const behindTeam = inferTeamForSide(behindSide);
    let pool;
    let teamName = null;
    if (behindTeam) {
      const roster = teamRosterNames(behindTeam);
      pool = rows.filter((r) => roster.has(r.name) && !allInTrade.has(r.name));
      teamName = behindTeam.name || null;
    }
    // Fallback when no team can be inferred (or the inferred team
    // has nothing left after subtracting what's already in the
    // trade).  Preserves existing behaviour when Sleeper data is
    // unavailable.
    if (!pool || pool.length === 0) {
      pool = rows.filter((r) => !allInTrade.has(r.name));
      teamName = null;
    }
    const list = findBalancers(pwGap, pool, valueMode);
    return { list, teamName };
  }, [pwGap, rows, sides, valueMode, inferTeamForSide, teamRosterNames]);

  // For 3+ teams, find balancers for the team getting the best deal
  // (they should add more to their give to even things out).  Uses
  // the destination-aware NET flow (received − given) so the target
  // is whoever profited most after each asset was routed to its
  // chosen destination.  Falling back to the raw total index would
  // pick whoever put the fewest pieces on the table — a different
  // question entirely.
  const multiBalancers = useMemo(() => {
    if (sides.length <= 2) return null;
    const nets = sideFlows.map((f) => f.net);
    const worstIdx = nets.indexOf(Math.min(...nets)); // most negative = overpaying
    const bestIdx = nets.indexOf(Math.max(...nets));  // most positive = getting a deal
    const gap = nets[bestIdx] - nets[worstIdx];
    if (gap < 350) return null;
    const allInTrade = new Set(sides.flatMap((s) => s.assets.map((a) => a.name)));
    // Panel renders on the side that needs to GIVE more (the one with
    // the best deal right now).  Filter the suggestion pool to that
    // side's Sleeper team so the "add more" list is players they
    // actually own.  Same fallback to full pool when inference fails.
    const underpayingSide = sides[bestIdx];
    const underpayingTeam = inferTeamForSide(underpayingSide);
    let pool;
    let teamName = null;
    if (underpayingTeam) {
      const roster = teamRosterNames(underpayingTeam);
      pool = rows.filter((r) => roster.has(r.name) && !allInTrade.has(r.name));
      teamName = underpayingTeam.name || null;
    }
    if (!pool || pool.length === 0) {
      pool = rows.filter((r) => !allInTrade.has(r.name));
      teamName = null;
    }
    const suggestions = findBalancers(gap, pool, valueMode);
    return {
      overpayingIdx: worstIdx,
      underpayingIdx: bestIdx, // panel rendered on the side that needs to give more
      gap,
      suggestions,
      teamName,
    };
  }, [sides, sideFlows, rows, valueMode, inferTeamForSide, teamRosterNames]);

  // All assets currently in any side (for picker exclusion)
  const allTradeNames = useMemo(() => {
    return new Set(sides.flatMap((s) => s.assets.map((r) => r.name)));
  }, [sides]);

  const pickerRows = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    let list = rows.filter((r) => !allTradeNames.has(r.name));
    if (pickerFilter !== "all") list = list.filter((r) => r.assetClass === pickerFilter);
    if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
    // Sort by selected column
    const dir = pickerSortAsc ? 1 : -1;
    list = [...list].sort((a, b) => {
      let va, vb;
      switch (pickerSortCol) {
        case "rank":
          va = a.blendedSourceRank ?? Infinity; vb = b.blendedSourceRank ?? Infinity;
          return (va - vb) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "pos":
          return (a.pos || "").localeCompare(b.pos || "") * dir;
        case "value":
          va = displayValue(a, settings); vb = displayValue(b, settings);
          return (va - vb) * dir;
        default: {
          if (typeof pickerSortCol === "string" && pickerSortCol.startsWith("src:")) {
            const key = pickerSortCol.slice(4);
            va = Number(a.canonicalSites?.[key]) || 0;
            vb = Number(b.canonicalSites?.[key]) || 0;
            return (va - vb) * dir;
          }
          va = a.blendedSourceRank ?? Infinity; vb = b.blendedSourceRank ?? Infinity;
          return (va - vb) * dir;
        }
      }
    });
    return list.slice(0, 100);
  }, [rows, allTradeNames, pickerQuery, pickerFilter, pickerSortCol, pickerSortAsc]);

  const recentRows = useMemo(() => recentNames.map((n) => rowByName.get(n)).filter(Boolean), [recentNames, rowByName]);

  function addRecent(name) {
    setRecentNames((prev) => {
      const next = [name, ...prev.filter((x) => x !== name)].slice(0, 20);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      return next;
    });
  }

  // ── Side management ─────────────────────────────────────────────────
  function addToSide(row, sideIdx) {
    if (!row) return;
    // Check all sides for duplicates
    if (allTradeNames.has(row.name)) return;
    setSides((prev) => prev.map((s, i) => {
      if (i !== sideIdx) return s;
      if (s.assets.some((r) => r.name === row.name)) return s;
      // 3+-team trades need an explicit destination per asset so the
      // fairness bar can compute each side's NET flow.  Seed the
      // default (next side, circular) whenever we're adding to a
      // multi-side trade.  2-team trades leave destinations empty —
      // ``computeSideFlows`` handles the implicit "other side" case.
      const nextDestinations = { ...(s.destinations || {}) };
      if (prev.length > 2) {
        nextDestinations[row.name] = defaultDestination(i, prev.length);
      }
      return {
        ...s,
        assets: [...s.assets, row],
        destinations: nextDestinations,
      };
    }));
    addRecent(row.name);
  }

  function setAssetDestination(sideIdx, assetName, destIdx) {
    setSides((prev) => prev.map((s, i) => {
      if (i !== sideIdx) return s;
      const next = { ...(s.destinations || {}) };
      next[assetName] = Number(destIdx);
      return { ...s, destinations: next };
    }));
  }

  function addToActiveSide(row) {
    addToSide(row, activeSide);
    // Tapping a result row blurs the search input, which drops the
    // iOS soft keyboard and makes the search bar feel like it "went
    // away" — the user then has to tap the field again to keep
    // adding players.  Re-focus the picker input so the keyboard
    // stays up and the field is ready for the next query.
    if (pickerOpen && pickerInputRef.current) {
      // Defer one tick so the React commit that removed the tapped
      // row has flushed before we re-focus.
      requestAnimationFrame(() => pickerInputRef.current?.focus({ preventScroll: true }));
    }
  }

  // Register add-to-trade callback so popup/search can add players
  useEffect(() => {
    registerAddToTrade?.(addToActiveSide);
    return () => registerAddToTrade?.(null);
  }, [registerAddToTrade, activeSide]); // eslint-disable-line react-hooks/exhaustive-deps

  function removeFromSide(name, sideIdx) {
    setSides((prev) => prev.map((s, i) => {
      if (i !== sideIdx) return s;
      const nextDestinations = { ...(s.destinations || {}) };
      delete nextDestinations[name];
      return {
        ...s,
        assets: s.assets.filter((r) => r.name !== name),
        destinations: nextDestinations,
      };
    }));
  }

  function clearTrade() {
    setSides((prev) => prev.map((s) => ({ ...s, assets: [], destinations: {} })));
  }

  function swapSides() {
    if (sides.length === 2) {
      setSides((prev) => [
        { ...prev[1], id: 0, label: "A" },
        { ...prev[0], id: 1, label: "B" },
      ]);
      setActiveSide((s) => s === 0 ? 1 : 0);
    } else {
      // Rotate: side i takes the previous side's assets.  Each asset
      // moves one slot forward, so its destination also rotates one
      // slot forward to preserve the user's chosen routing.
      setSides((prev) => {
        const n = prev.length;
        return prev.map((s, i) => {
          const srcIdx = (i + n - 1) % n;
          const src = prev[srcIdx];
          const nextDestinations = {};
          for (const [name, dest] of Object.entries(src.destinations || {})) {
            const parsed = Number(dest);
            if (!Number.isInteger(parsed)) continue;
            const rotated = (parsed + 1) % n;
            // Drop self-references that could sneak in post-rotation;
            // ``defaultDestination`` will take over in ``computeSideFlows``.
            if (rotated !== i) nextDestinations[name] = rotated;
          }
          return {
            id: i,
            label: SIDE_LABELS[i],
            assets: src.assets,
            destinations: nextDestinations,
          };
        });
      });
    }
  }

  function addTeam() {
    if (sides.length >= MAX_SIDES) return;
    setSides((prev) => {
      const newCount = prev.length + 1;
      // Going from N → N+1.  When the previous trade was 2-team the
      // assets had implicit "other side" destinations; now we need
      // explicit ones so the NET flow math has a valid starting point.
      // Seed the default (next side circular) for any asset that
      // doesn't already have an entry.  Assets that already have a
      // destination keep it — the user's chosen routing is preserved.
      const withDestinations = prev.map((s, i) => {
        const nextDest = { ...(s.destinations || {}) };
        for (const asset of s.assets) {
          if (nextDest[asset.name] == null) {
            nextDest[asset.name] = defaultDestination(i, newCount);
          }
        }
        return { ...s, destinations: nextDest };
      });
      return [...withDestinations, createSide(prev.length)];
    });
  }

  function removeTeam(idx) {
    if (sides.length <= MIN_SIDES) return;
    setSides((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      const newCount = next.length;
      // Reletter remaining sides AND rewrite destinations so any
      // asset that was targeting the removed side — or one of the
      // now-shifted sides — points at a valid slot.  Destinations
      // that would collapse onto the side itself fall back to the
      // default (next side circular).
      return next.map((s, i) => {
        const remapped = {};
        for (const [name, dest] of Object.entries(s.destinations || {})) {
          const parsed = Number(dest);
          if (!Number.isInteger(parsed)) continue;
          if (parsed === idx) {
            // Asset was going to the removed side — reassign.
            remapped[name] = defaultDestination(i, newCount);
            continue;
          }
          const shifted = parsed > idx ? parsed - 1 : parsed;
          if (shifted >= 0 && shifted < newCount && shifted !== i) {
            remapped[name] = shifted;
          } else {
            remapped[name] = defaultDestination(i, newCount);
          }
        }
        return {
          ...s,
          id: i,
          label: SIDE_LABELS[i],
          destinations: remapped,
        };
      });
    });
    // Fix activeSide if it's out of bounds
    setActiveSide((prev) => Math.min(prev, sides.length - 2));
  }

  function openPickerFor(sideIdx) { setActiveSide(sideIdx); setPickerOpen(true); }

  // ── KTC trade-calculator URL import ───────────────────────────────
  // Paste a https://keeptradecut.com/trade-calculator?teamOne=...&teamTwo=...
  // URL, POST to the backend for name resolution, then replace Sides
  // A and B with the resolved rows.  Any sides beyond B are kept
  // untouched so a 3-team trade doesn't lose its 3rd slot just
  // because a 2-side KTC URL was imported.  Unresolved KTC IDs
  // surface as a warning in ``ktcImportStatus`` so the user knows
  // one or more pieces were dropped.
  const importKtcTradeUrl = useCallback(async () => {
    const url = (ktcImportUrl || "").trim();
    if (!url) {
      setKtcImportError("Paste a KTC trade-calculator URL first.");
      return;
    }
    if (!url.includes("keeptradecut.com")) {
      setKtcImportError("URL must be from keeptradecut.com.");
      return;
    }

    setKtcImportBusy(true);
    setKtcImportError("");
    setKtcImportStatus("");
    try {
      const res = await fetch("/api/trade/import-ktc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.ok === false) {
        setKtcImportError(data?.error || `HTTP ${res.status}`);
        return;
      }

      const sideOneEntries = Array.isArray(data.sideOne) ? data.sideOne : [];
      const sideTwoEntries = Array.isArray(data.sideTwo) ? data.sideTwo : [];
      const unresolvedOne = data?.unresolved?.sideOne || [];
      const unresolvedTwo = data?.unresolved?.sideTwo || [];

      // Resolve each KTC-returned name → our canonical row.  Our
      // board and KTC share pick-name shapes ("2026 Early 1st") and
      // most player names verbatim, so a direct rowByName hit
      // covers the common case.  For near-matches we try a ladder
      // of increasingly permissive lookups (case-insensitive,
      // whitespace-normalized, suffix-stripped) before giving up —
      // historically this silently dropped picks + "Jr./III"
      // variants.  Residual misses are surfaced to the user.
      const _normalize = (s) =>
        String(s || "")
          .toLowerCase()
          .replace(/[.']/g, "")
          .replace(/\s+/g, " ")
          .replace(/\s+(jr|sr|ii|iii|iv|v)$/i, "")
          .trim();
      const lowerIndex = new Map();
      const normIndex = new Map();
      for (const r of rows) {
        if (!r?.name) continue;
        const low = r.name.toLowerCase();
        if (!lowerIndex.has(low)) lowerIndex.set(low, r);
        const norm = _normalize(r.name);
        if (!normIndex.has(norm)) normIndex.set(norm, r);
      }
      const resolveBatch = (entries) => {
        const found = [];
        const missing = [];
        for (const entry of entries) {
          // 1. Exact case match — fast path, covers 99%.
          let row = rowByName.get(entry.name);
          // 2. Case-insensitive match.
          if (!row) row = lowerIndex.get(String(entry.name || "").toLowerCase());
          // 3. Normalized (punctuation / whitespace / suffix-stripped).
          if (!row) row = normIndex.get(_normalize(entry.name));
          // 4. Pick token fallback — KTC's pick labels ("2026 1.09",
          //    "2027 Mid 1st") use a different shape than our
          //    canonical row names ("2026 Pick 1.09").  Walk the
          //    same ``resolvePickRow`` resolver league-analysis +
          //    the share-URL hydrator use so picks from KTC URLs
          //    actually load instead of silently dropping.
          if (!row && parsePickToken(entry.name)) {
            row = resolvePickRow(entry.name, rowByLowerName, pickAliases);
          }
          if (row) found.push(row);
          else missing.push(entry.name);
        }
        return { found, missing };
      };
      const one = resolveBatch(sideOneEntries);
      const two = resolveBatch(sideTwoEntries);

      // Replace sides A and B in place, dedup per-side and across
      // sides (addToSide normally does this — we mirror that guard
      // here since we're bypassing it for a bulk set).
      const seen = new Set();
      const clean = (rowsIn) => {
        const out = [];
        for (const r of rowsIn) {
          if (!r || seen.has(r.name)) continue;
          seen.add(r.name);
          out.push(r);
        }
        return out;
      };
      const cleanedOne = clean(one.found);
      const cleanedTwo = clean(two.found);

      setSides((prev) => prev.map((s, i) => {
        if (i !== 0 && i !== 1) return s; // leave 3rd+ sides alone
        const replacement = i === 0 ? cleanedOne : cleanedTwo;
        // Seed default destinations for the newly-loaded assets when
        // we're in a 3+-team trade; 2-team trades ignore the map.
        // Old destinations referencing assets that aren't in the new
        // set are dropped so we don't accumulate stale routing.
        const nextDestinations = {};
        if (prev.length > 2) {
          for (const asset of replacement) {
            nextDestinations[asset.name] = defaultDestination(i, prev.length);
          }
        }
        return { ...s, assets: replacement, destinations: nextDestinations };
      }));

      const warnings = [];
      if (unresolvedOne.length) warnings.push(`unknown KTC id(s) on side A: ${unresolvedOne.join(", ")}`);
      if (unresolvedTwo.length) warnings.push(`unknown KTC id(s) on side B: ${unresolvedTwo.join(", ")}`);
      if (one.missing.length) warnings.push(`no board match for: ${one.missing.join(", ")}`);
      if (two.missing.length) warnings.push(`no board match for: ${two.missing.join(", ")}`);
      const totalLoaded = cleanedOne.length + cleanedTwo.length;
      const totalExpected = sideOneEntries.length + sideTwoEntries.length;
      if (totalLoaded === 0) {
        setKtcImportError(
          warnings.length
            ? `Nothing loaded — ${warnings.join("; ")}`
            : "Nothing loaded.",
        );
      } else {
        const summary = `Loaded ${totalLoaded}/${totalExpected} players`;
        setKtcImportStatus(
          warnings.length ? `${summary} — ${warnings.join("; ")}` : summary,
        );
        // Collapse the import row on success so the user isn't
        // staring at the URL field; leave status visible below.
        setKtcImportOpen(false);
      }
    } catch (err) {
      setKtcImportError(err?.message || "Import failed");
    } finally {
      setKtcImportBusy(false);
    }
  }, [ktcImportUrl, rowByName]);

  // ── Share-URL + simulator actions ─────────────────────────────────
  // Build a share-URL from the current trade and copy to clipboard.
  // Falls back to selecting the URL in a prompt when the clipboard
  // API is unavailable (older Safari / non-HTTPS contexts).
  const copyShareLink = useCallback(async () => {
    try {
      const payload = {
        sides: sides.map((s) => ({
          name: s.label ? `Side ${s.label}` : "",
          players: (s.assets || []).map((a) => a.name),
        })),
      };
      const url = buildShareUrl(payload);
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShareStatus("Share link copied to clipboard.");
      } else if (typeof window !== "undefined") {
        // Surface the URL so the user can copy it manually.
        window.prompt("Copy this share link:", url);
        setShareStatus("Share link ready.");
      }
    } catch (err) {
      setShareStatus(err?.message || "Could not copy share link.");
    }
  }, [sides]);

  // Pure impact-on-my-roster simulator.  2-team trades only:
  // whichever side matches the user's selected Sleeper team is
  // treated as "sending" (players OUT) and the other side as
  // "receiving" (players IN).  Picks and players are sent as one
  // payload each because the simulator backend treats them
  // identically — both resolve through the same row-index.
  const runSimulateTrade = useCallback(() => {
    if (sides.length !== 2) return;
    if (!selectedTeam) return;
    const myRosterNames = teamRosterNames(selectedTeam);
    // Score each side by how many of its assets the user owns.
    // Whichever side has more matches is "my side" (I'm giving).
    const scores = sides.map((s) => {
      let hits = 0;
      for (const a of s.assets || []) if (myRosterNames.has(a.name)) hits += 1;
      return hits;
    });
    let mySide = scores[0] >= scores[1] ? 0 : 1;
    if (scores[0] === 0 && scores[1] === 0) {
      // Neither side matches — default to "I'm giving side A" so the
      // user can flip via Swap Sides if needed.
      mySide = 0;
    }
    const otherSide = mySide === 0 ? 1 : 0;
    const isPickName = (name) => /\d{4}/.test(String(name || ""));
    const playersOut = [];
    const picksOut = [];
    for (const a of sides[mySide].assets || []) {
      if (isPickName(a.name)) picksOut.push(a.name);
      else playersOut.push(a.name);
    }
    const playersIn = [];
    const picksIn = [];
    for (const a of sides[otherSide].assets || []) {
      if (isPickName(a.name)) picksIn.push(a.name);
      else playersIn.push(a.name);
    }
    simulateTrade({
      teamName: selectedTeam?.name,
      playersIn,
      playersOut,
      picksIn,
      picksOut,
    });
  }, [sides, selectedTeam, teamRosterNames, simulateTrade]);

  // ── Suggestions logic ─────────────────────────────────────────────
  const parseRoster = useCallback(() => {
    return rosterInput
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [rosterInput]);

  function selectTeam(idx) {
    const i = Number(idx);
    setSelectedTeamIdx(i);
    localStorage.setItem(TEAM_KEY, String(i));

    if (i < 0 || !sleeperTeams || !sleeperTeams[i]) {
      setLeagueRosters(null);
      return;
    }

    const team = sleeperTeams[i];
    const picks = (team.picks || []).map((p) => {
      const m = p.match(/^(\d{4})\s+(\d)\./);
      if (m) {
        const round = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th" }[m[2]] || `${m[2]}th`;
        return `${m[1]} ${round}`;
      }
      return p.replace(/\s*\(.*\)/, "").trim();
    });
    const rosterNames = [...(team.players || []), ...picks];
    const newInput = rosterNames.join("\n");
    setRosterInput(newInput);
    localStorage.setItem(ROSTER_KEY, newInput);

    const opponents = sleeperTeams
      .filter((_, oi) => oi !== i)
      .map((t) => ({ team_name: t.name, players: t.players || [] }));
    setLeagueRosters(opponents);
  }

  // Auto-fetch suggestions whenever the user lands on the page with
  // a populated roster — surfaces the proactive "Recommended right
  // now" rail without requiring the user to scroll down + click
  // ``Get Suggestions`` first.  Re-fires when:
  //   * roster contents change (paste / reset)
  //   * selected league/team changes (incl. picks regenerate)
  //   * loading completes (cold-load arrives after first paint)
  // Debounced via a ref so a rapid roster edit doesn't spam the API.
  const proactiveFetchRef = useRef({ lastBody: null, timer: null });
  useEffect(() => {
    if (loading || error || leagueMismatch) return;
    if (!rows || rows.length === 0) return;
    const roster = parseRoster();
    if (roster.length < 3) return;
    const bodyKey = `${selectedLeagueKey || ""}|${roster.join("|")}`;
    if (proactiveFetchRef.current.lastBody === bodyKey) return;
    proactiveFetchRef.current.lastBody = bodyKey;
    if (proactiveFetchRef.current.timer) {
      clearTimeout(proactiveFetchRef.current.timer);
    }
    proactiveFetchRef.current.timer = setTimeout(() => {
      // Only auto-fetch if we don't already have suggestions for this
      // roster — preserves manually-fetched results.
      if (!suggestions) fetchSuggestions();
    }, 500);
    return () => {
      if (proactiveFetchRef.current.timer) {
        clearTimeout(proactiveFetchRef.current.timer);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, error, leagueMismatch, rows, rosterInput, selectedLeagueKey]);

  async function fetchSuggestions() {
    const roster = parseRoster();
    if (roster.length < 3) {
      setSuggestionsError("Enter at least 3 player names to get suggestions.");
      return;
    }
    setSuggestionsLoading(true);
    setSuggestionsError(null);
    setSuggestions(null);
    localStorage.setItem(ROSTER_KEY, rosterInput);
    try {
      // Attach the active league key so the backend validates
      // against the registry and serves/rejects for the right
      // league.  The endpoint falls back to the user's saved
      // preference when leagueKey is absent, but passing it
      // explicitly keeps the response league unambiguous when the
      // user has just switched leagues and the new key hasn't
      // round-tripped to user_kv yet.
      const body = leagueRosters
        ? { roster, league_rosters: leagueRosters }
        : { roster };
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
      const res = await fetch("/api/trade/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setSuggestionsError(data.error || `Server error (${res.status})`);
        return;
      }
      setSuggestions(data);
    } catch (err) {
      setSuggestionsError("Could not reach suggestion service.");
    } finally {
      setSuggestionsLoading(false);
    }
  }

  function applySuggestion(s) {
    const giveRows = s.give.map((p) => rowByName.get(p.name)).filter(Boolean);
    const recvRows = s.receive.map((p) => rowByName.get(p.name)).filter(Boolean);
    // Apply to first two sides, reset others.  Suggestions are
    // inherently 2-team; wipe the 3rd+ side contents (and their
    // destination maps) so stale multi-team routing doesn't linger.
    setSides((prev) => {
      const sideCount = prev.length;
      const seedDestinations = (assets, sideIdx) => {
        if (sideCount <= 2) return {};
        const out = {};
        for (const asset of assets) {
          out[asset.name] = defaultDestination(sideIdx, sideCount);
        }
        return out;
      };
      return prev.map((side, i) => {
        if (i === 0) return { ...side, assets: giveRows, destinations: seedDestinations(giveRows, 0) };
        if (i === 1) return { ...side, assets: recvRows, destinations: seedDestinations(recvRows, 1) };
        return { ...side, assets: [], destinations: {} };
      });
    });
  }

  // Count per category
  const suggestionCounts = useMemo(() => {
    if (!suggestions) return {};
    return Object.fromEntries(SUGG_TYPES.map((t) => [t.key, (suggestions[t.key] || []).length]));
  }, [suggestions]);

  // Determine grid columns class for the sides container
  const sidesGridClass = sides.length === 2
    ? "trade-sides-grid trade-sides-2"
    : sides.length === 3
      ? "trade-sides-grid trade-sides-3"
      : "trade-sides-grid trade-sides-multi";

  return (
    <section className="card">
      <h1 style={{ marginTop: 0 }}>Trade Builder</h1>
      <p className="muted" style={{ marginTop: 4 }}>Multi-team trade calculator with live fairness visualization.</p>

      {loading && <p>Loading player pool...</p>}
      {!!error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && leagueMismatch && (
        <div
          className="card"
          style={{
            marginBottom: 10,
            padding: "8px 12px",
            border: "1px solid var(--cyan)",
            background: "rgba(255, 199, 4, 0.05)",
            fontSize: "0.78rem",
          }}
        >
          <strong style={{ color: "var(--cyan)" }}>Roster data not ready for this league.</strong>{" "}
          Rankings + values are available (scoring is shared), but team-specific
          features — Sleeper roster import, the "Simulate on my team" button,
          and league-mate pickers — need this league&apos;s scrape to complete
          first.  Switch back to the primary league from the nav to use those
          features.
        </div>
      )}

      {/* Proactive "Recommended right now" rail.  Surfaces top
          suggestion from each category when ``/api/trade/suggestions``
          has a non-empty result for the user's roster.  Each card
          previews the give/get and one-click-applies the suggestion
          to the trade builder below. */}
      {!loading && !error && !leagueMismatch && suggestions && suggestions.totalSuggestions > 0 && (
        <ProactiveSuggestionsRail
          suggestions={suggestions}
          onApply={(s) => {
            applySuggestion(s);
            // Scroll into view so the user sees the populated builder.
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
        />
      )}

      {!loading && !error && (
        <>
          <div className="row trade-controls" style={{ marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
            <select className="select" value={valueMode} onChange={(e) => setValueMode(e.target.value)}>
              {VALUE_MODES.map((m) => (<option key={m.key} value={m.key}>{m.label}</option>))}
            </select>
            <button className="button" onClick={swapSides}>
              {sides.length === 2 ? "Swap Sides" : "Rotate Sides"}
            </button>
            <button className="button" onClick={clearTrade}>Clear Trade</button>
            {sides.length < MAX_SIDES && (
              <button className="button" onClick={addTeam} style={{ borderColor: "var(--green)", color: "var(--green)" }}>
                + Add Team
              </button>
            )}
            <button
              className="button"
              onClick={() => {
                setKtcImportOpen((v) => !v);
                setKtcImportError("");
              }}
              style={{ borderColor: "var(--cyan)", color: "var(--cyan)" }}
              title="Paste a KeepTradeCut trade-calculator URL to load its players into sides A + B"
            >
              + Import KTC
            </button>
            <button
              className="button"
              onClick={copyShareLink}
              disabled={!sides.some((s) => (s.assets || []).length > 0)}
              style={{ borderColor: "var(--cyan)", color: "var(--cyan)" }}
              title="Copy a shareable link that pre-loads this trade for anyone who opens it"
            >
              🔗 Copy Share Link
            </button>
            {sides.length === 2 && selectedTeam && (
              <button
                className="button"
                onClick={runSimulateTrade}
                disabled={simLoading || !sides.some((s) => (s.assets || []).length > 0)}
                style={{ borderColor: "var(--green)", color: "var(--green)" }}
                title={`Apply this trade to ${selectedTeam.name} and see before/after roster value`}
              >
                {simLoading ? "Simulating…" : "⚙ Simulate impact"}
              </button>
            )}
          </div>

          {shareStatus && (
            <div
              className="muted"
              style={{
                fontSize: "0.74rem",
                marginBottom: 8,
                paddingLeft: 2,
              }}
            >
              <span style={{ color: "var(--cyan)" }}>Share:</span>{" "}
              {shareStatus}
              <button
                className="button"
                style={{
                  marginLeft: 8,
                  padding: "1px 8px",
                  fontSize: "0.66rem",
                  minHeight: "unset",
                }}
                onClick={() => setShareStatus("")}
                title="Dismiss"
              >
                ×
              </button>
            </div>
          )}

          {(simResult || simError) && (
            <div
              className="card"
              style={{
                marginBottom: 10,
                padding: "10px 12px",
                border: "1px solid var(--green)",
                background: "rgba(52,211,153,0.05)",
              }}
            >
              <div style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 8,
              }}>
                <div style={{ fontSize: "0.74rem", fontWeight: 700, letterSpacing: "0.04em" }}>
                  IMPACT ON {simResult?.team?.name?.toUpperCase?.() || (selectedTeam?.name || "").toUpperCase()}
                </div>
                <button
                  className="button"
                  style={{ fontSize: "0.66rem", padding: "1px 8px", minHeight: "unset" }}
                  onClick={resetSim}
                  title="Clear simulation"
                >
                  ×
                </button>
              </div>
              {simError && (
                <div style={{ color: "var(--red)", fontSize: "0.78rem" }}>
                  {simError}
                </div>
              )}
              {simResult && (
                <div>
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, minmax(0,1fr))",
                    gap: 10,
                    marginBottom: 8,
                  }}>
                    <div>
                      <div className="muted" style={{ fontSize: "0.66rem" }}>Before</div>
                      <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>
                        {Math.round(simResult.before?.totalValue || 0).toLocaleString()}
                      </div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: "0.66rem" }}>After</div>
                      <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>
                        {Math.round(simResult.after?.totalValue || 0).toLocaleString()}
                      </div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: "0.66rem" }}>Δ Total Value</div>
                      <div style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color: (simResult.delta?.totalValue || 0) >= 0 ? "var(--green)" : "var(--red)",
                      }}>
                        {(simResult.delta?.totalValue || 0) >= 0 ? "+" : ""}
                        {Math.round(simResult.delta?.totalValue || 0).toLocaleString()}
                      </div>
                    </div>
                  </div>
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))",
                    gap: 8,
                    fontSize: "0.72rem",
                  }}>
                    {["QB", "RB", "WR", "TE"].map((pos) => {
                      const row = simResult.delta?.byPosition?.[pos];
                      if (!row) return null;
                      const d = row.value || 0;
                      return (
                        <div key={pos} style={{
                          padding: "4px 8px",
                          border: "1px solid var(--border)",
                          borderRadius: 4,
                        }}>
                          <span className="muted">{pos}</span>{" "}
                          <span style={{
                            color: d === 0 ? "var(--muted)" : d > 0 ? "var(--green)" : "var(--red)",
                            fontWeight: 600,
                          }}>
                            {d > 0 ? "+" : ""}{Math.round(d).toLocaleString()}
                          </span>
                          {row.count !== 0 && (
                            <span className="muted" style={{ marginLeft: 4 }}>
                              ({row.count > 0 ? "+" : ""}{row.count})
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {(simResult.unresolvedIn?.length > 0 || simResult.unresolvedOut?.length > 0) && (
                    <div className="muted" style={{ fontSize: "0.7rem", marginTop: 6, color: "var(--red)" }}>
                      Unresolved:{" "}
                      {[...(simResult.unresolvedIn || []), ...(simResult.unresolvedOut || [])].join(", ")}
                    </div>
                  )}
                  <div className="muted" style={{ fontSize: "0.68rem", marginTop: 6 }}>
                    Equity (receiving − sending): {simResult.equity >= 0 ? "+" : ""}
                    {Math.round(simResult.equity || 0).toLocaleString()}
                  </div>
                </div>
              )}
            </div>
          )}

          {ktcImportOpen && (
            <div
              className="card"
              style={{
                marginBottom: 10,
                padding: "10px 12px",
                border: "1px solid var(--cyan)",
                background: "rgba(255, 199, 4,0.04)",
              }}
            >
              <div style={{ fontSize: "0.74rem", fontWeight: 700, letterSpacing: "0.04em", marginBottom: 6 }}>
                IMPORT FROM KEEPTRADECUT
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <input
                  type="text"
                  className="input"
                  placeholder="https://keeptradecut.com/trade-calculator?teamOne=…&teamTwo=…"
                  value={ktcImportUrl}
                  onChange={(e) => setKtcImportUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !ktcImportBusy) importKtcTradeUrl();
                    if (e.key === "Escape") {
                      setKtcImportOpen(false);
                      setKtcImportError("");
                    }
                  }}
                  disabled={ktcImportBusy}
                  style={{ flex: "1 1 360px", minWidth: 260 }}
                  autoFocus
                />
                <button
                  className="button"
                  onClick={importKtcTradeUrl}
                  disabled={ktcImportBusy || !ktcImportUrl.trim()}
                  style={{ borderColor: "var(--cyan)", color: "var(--cyan)" }}
                >
                  {ktcImportBusy ? "Loading…" : "Load trade"}
                </button>
                <button
                  className="button"
                  onClick={() => {
                    setKtcImportOpen(false);
                    setKtcImportError("");
                    setKtcImportUrl("");
                  }}
                  disabled={ktcImportBusy}
                >
                  Cancel
                </button>
              </div>
              <div className="muted" style={{ fontSize: "0.72rem", marginTop: 6 }}>
                Replaces sides A and B; extra sides (3+ team trades) are left untouched.
                Unknown KTC IDs and players we can't match by name are reported below.
              </div>
              {ktcImportError && (
                <div style={{ color: "var(--red)", fontSize: "0.76rem", marginTop: 6 }}>
                  {ktcImportError}
                </div>
              )}
            </div>
          )}

          {ktcImportStatus && !ktcImportOpen && (
            <div
              className="muted"
              style={{
                fontSize: "0.74rem",
                marginBottom: 8,
                paddingLeft: 2,
              }}
            >
              <span style={{ color: "var(--cyan)" }}>KTC import:</span>{" "}
              {ktcImportStatus}
              <button
                className="button"
                style={{
                  marginLeft: 8,
                  padding: "1px 8px",
                  fontSize: "0.66rem",
                  minHeight: "unset",
                }}
                onClick={() => setKtcImportStatus("")}
                title="Dismiss"
              >
                ×
              </button>
            </div>
          )}

          {/* ── Trade Meter (inline fairness visualization) ──────── */}
          <TradeMeter sides={sides} sideTotals={sideTotals} flows={sideFlows} valueMode={valueMode} settings={settings} />

          {/* ── Per-source winner breakdown (below the fairness meter) ── */}
          <TradeSourceBreakdown sides={sides} settings={settings} />

          {/* ── Value delta histogram (graphical complement to meter) ──── */}
          {sides.length === 2 ? (
            <div className="card" style={{ padding: "var(--space-sm) var(--space-md)" }}>
              <TradeDeltaHistogram
                sides={[
                  {
                    label: `Side ${sides[0]?.label || "A"}`,
                    total: sideTotals[0]?.adjusted || 0,
                  },
                  {
                    label: `Side ${sides[1]?.label || "B"}`,
                    total: sideTotals[1]?.adjusted || 0,
                  },
                ]}
              />
            </div>
          ) : null}

          {/* Multi-team Sankey-style flow visual.  Only renders when
              there are 3+ sides — the existing 2-team trade meter
              already makes flow obvious for a 1-on-1 deal.  Reads
              the same ``sideFlowAssets`` the side cards consume so
              the picture stays in lockstep with what each side
              shows. */}
          {sides.length >= 3 && (
            <MultiTradeFlow
              sides={sides}
              sideFlowAssets={sideFlowAssets}
              valueMode={valueMode}
              settings={settings}
            />
          )}

          {/* ── Side Cards ──────────────────────────────────────── */}
          <div className={sidesGridClass} style={{ paddingBottom: 78 }}>
            {sides.map((side, sideIdx) => {
              const total = sideTotals[sideIdx] || { raw: 0, adjustment: 0, adjusted: 0 };
              const isOverpaying = sides.length === 2
                ? (sideIdx === 0 ? pwGap > 350 : pwGap < -350)
                : false;
              const isUnderpaying = sides.length === 2
                ? (sideIdx === 0 ? pwGap < -350 : pwGap > 350)
                : false;

              const isMySide = sideIdx === mySideIdx;
              return (
                <div
                  className="card"
                  key={side.id}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    // Subtle gold accent on the user's own side so it
                    // stays visually identifiable even after the tray
                    // scrolls or the user adds/removes assets.
                    borderColor: isMySide ? "rgba(255, 199, 4, 0.4)" : undefined,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <h3 style={{ margin: 0 }}>Side {side.label}</h3>
                      {isMySide && selectedTeam?.name && (
                        <span
                          className="badge"
                          title={`This side matches your roster: ${selectedTeam.name}`}
                          style={{
                            fontSize: "0.6rem",
                            padding: "2px 6px",
                            color: "var(--cyan)",
                            borderColor: "rgba(255, 199, 4, 0.45)",
                            background: "rgba(255, 199, 4, 0.08)",
                          }}
                        >
                          You · {selectedTeam.name}
                        </span>
                      )}
                      {sides.length > MIN_SIDES && (
                        <button
                          className="button button-danger"
                          style={{ fontSize: "0.66rem", padding: "2px 6px", minHeight: "unset" }}
                          onClick={() => removeTeam(sideIdx)}
                          title={`Remove Side ${side.label}`}
                        >
                          X
                        </button>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ textAlign: "right" }}>
                        <div className="value">{Math.round(total.adjusted).toLocaleString()}</div>
                        {total.adjustment > 0 ? (
                          <div
                            className="muted"
                            style={{ fontSize: "0.64rem", color: "var(--cyan)" }}
                            title="Consolidation / roster-spot premium: the side with fewer pieces frees up a roster spot, so KTC-style math adds this bonus on top of the raw total."
                          >
                            Raw {Math.round(total.raw).toLocaleString()} + VA {Math.round(total.adjustment).toLocaleString()}
                          </div>
                        ) : (
                          <div className="muted" style={{ fontSize: "0.64rem" }}>Raw: {Math.round(total.raw).toLocaleString()}</div>
                        )}
                      </div>
                      <button className="button trade-add-btn" onClick={() => openPickerFor(sideIdx)}>+ Add</button>
                    </div>
                  </div>
                  {sides.length > 2 && (
                    <div
                      className="label"
                      style={{
                        marginTop: 10,
                        fontSize: "0.68rem",
                        color: "var(--red)",
                        letterSpacing: "0.05em",
                      }}
                    >
                      GIVING
                    </div>
                  )}
                  <div className="list" style={{ marginTop: sides.length > 2 ? 4 : 10 }}>
                    {side.assets.map((r) => {
                      const edge = getPlayerEdge(r);
                      // In 3+-team trades, each asset has an explicit
                      // destination side so the fairness bar can compute
                      // per-team NET flow.  The dropdown is rendered
                      // only when N > 2; for 2-team trades the other
                      // side is implicit and the dropdown is hidden.
                      const storedDest = side.destinations?.[r.name];
                      const parsedDest = Number(storedDest);
                      const currentDest =
                        Number.isInteger(parsedDest) &&
                        parsedDest >= 0 &&
                        parsedDest < sides.length &&
                        parsedDest !== sideIdx
                          ? parsedDest
                          : defaultDestination(sideIdx, sides.length);
                      return (
                        <div className="asset-row" key={`${side.label}-${r.name}`}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                            <PlayerImage
                              playerId={r.raw?.playerId}
                              team={r.team}
                              position={r.pos}
                              name={r.name}
                              size={28}
                            />
                            <div style={{ minWidth: 0 }}>
                              <div className="asset-name">
                                <span style={{ cursor: "pointer", textDecoration: "underline dotted" }} onClick={() => openPlayerPopup?.(r)}>{r.name}</span>
                                {edge.signal && (
                                  <span className="badge" style={{ marginLeft: 6, fontSize: "0.6rem", padding: "1px 4px",
                                    color: edge.signal === "BUY" ? "var(--green)" : "var(--red)",
                                    borderColor: edge.signal === "BUY" ? "var(--green)" : "var(--red)" }}>
                                    {edge.signal} {edge.edgePct}%
                                  </span>
                                )}
                              </div>
                              <div className="asset-meta">{r.pos} · Consensus {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "—"} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
                            </div>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            {sides.length > 2 && (
                              <label
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 4,
                                  fontSize: "0.68rem",
                                }}
                                title="Which side this asset is going to"
                              >
                                <span className="muted" style={{ fontSize: "0.66rem" }}>→</span>
                                <select
                                  className="select trade-dest-select"
                                  value={currentDest}
                                  onChange={(e) => setAssetDestination(sideIdx, r.name, e.target.value)}
                                  style={{
                                    padding: "2px 4px",
                                    minHeight: "unset",
                                    height: "auto",
                                  }}
                                >
                                  {sides.map((s, i) =>
                                    i === sideIdx ? null : (
                                      <option key={i} value={i}>
                                        Side {s.label}
                                      </option>
                                    ),
                                  )}
                                </select>
                              </label>
                            )}
                            <button className="button trade-remove-btn" onClick={() => removeFromSide(r.name, sideIdx)}>Remove</button>
                          </div>
                        </div>
                      );
                    })}
                    {side.assets.length === 0 && <div className="muted">No assets yet.</div>}
                  </div>
                  {/* Receiving section — 3+-team mode only.  Shows the
                      assets that other sides have routed to THIS side,
                      so each card answers both "what am I giving up?"
                      and "what am I getting back?" in the same place. */}
                  {sides.length > 2 && (
                    <>
                      <div
                        className="label"
                        style={{
                          marginTop: 10,
                          fontSize: "0.68rem",
                          color: "var(--green)",
                          letterSpacing: "0.05em",
                        }}
                      >
                        RECEIVING
                      </div>
                      <div className="list" style={{ marginTop: 4 }}>
                        {(sideFlowAssets[sideIdx]?.incoming || []).length > 0 ? (
                          sideFlowAssets[sideIdx].incoming.map(({ asset, fromSideIdx }) => {
                            const edge = getPlayerEdge(asset);
                            return (
                              <div
                                className="asset-row"
                                key={`recv-${side.label}-${asset.name}`}
                                style={{ borderLeft: "2px solid var(--green)", paddingLeft: 6 }}
                              >
                                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                                  <PlayerImage
                                    playerId={asset.raw?.playerId}
                                    team={asset.team}
                                    position={asset.pos}
                                    name={asset.name}
                                    size={24}
                                  />
                                <div style={{ minWidth: 0 }}>
                                  <div className="asset-name">
                                    <span
                                      style={{ cursor: "pointer", textDecoration: "underline dotted" }}
                                      onClick={() => openPlayerPopup?.(asset)}
                                    >
                                      {asset.name}
                                    </span>
                                    {edge.signal && (
                                      <span
                                        className="badge"
                                        style={{
                                          marginLeft: 6,
                                          fontSize: "0.6rem",
                                          padding: "1px 4px",
                                          color: edge.signal === "BUY" ? "var(--green)" : "var(--red)",
                                          borderColor: edge.signal === "BUY" ? "var(--green)" : "var(--red)",
                                        }}
                                      >
                                        {edge.signal} {edge.edgePct}%
                                      </span>
                                    )}
                                  </div>
                                  <div className="asset-meta">
                                    {asset.pos} · from Side {sides[fromSideIdx]?.label || "?"} ·{" "}
                                    {Math.round(effectiveValue(asset, valueMode, settings)).toLocaleString()}
                                  </div>
                                </div>
                                </div>
                              </div>
                            );
                          })
                        ) : (
                          <div className="muted" style={{ fontSize: "0.72rem" }}>
                            Nothing incoming. Assign a destination on another side to route here.
                          </div>
                        )}
                      </div>
                    </>
                  )}
                  {/* Balancers (2-team mode only) */}
                  {sides.length === 2 && isUnderpaying && balancers.list.length > 0 && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(255, 199, 4,0.06)", borderRadius: 6 }}>
                      <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>
                        {balancers.teamName
                          ? `Add from ${balancers.teamName}'s roster:`
                          : "To balance, consider adding:"}
                      </div>
                      {balancers.list.map((b) => (
                        <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                          onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, sideIdx); }}>
                          {b.name} ({b.pos}) · {b.value.toLocaleString()}
                        </button>
                      ))}
                    </div>
                  )}
                  {/* Balancers (3+ team mode) - show on the side getting the best deal */}
                  {multiBalancers && sideIdx === multiBalancers.underpayingIdx && multiBalancers.suggestions.length > 0 && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(255, 199, 4,0.06)", borderRadius: 6 }}>
                      <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>
                        {multiBalancers.teamName
                          ? `Add from ${multiBalancers.teamName}'s roster (Side ${sides[multiBalancers.overpayingIdx]?.label} loses ${Math.round(multiBalancers.gap).toLocaleString()}):`
                          : `To balance (Side ${sides[multiBalancers.overpayingIdx]?.label} loses ${Math.round(multiBalancers.gap).toLocaleString()}):`}
                      </div>
                      {multiBalancers.suggestions.map((b) => (
                        <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                          onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, sideIdx); }}>
                          {b.name} ({b.pos}) · {b.value.toLocaleString()}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* ── Suggestions Panel ─────────────────────────────────── */}
          <div className="card" style={{ marginTop: 12 }}>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Trade Suggestions</h2>
            <p className="muted" style={{ margin: "4px 0 10px", fontSize: "0.76rem" }}>
              {sleeperTeams
                ? "Select your team from the league, or enter a roster manually."
                : "Enter your roster to get roster-aware trade ideas."}
            </p>

            {/* Team selector from Sleeper league */}
            {sleeperTeams && (
              <div className="row" style={{ marginBottom: 8, alignItems: "center" }}>
                <select
                  className="select"
                  value={selectedTeamIdx}
                  onChange={(e) => selectTeam(e.target.value)}
                  style={{ flex: 1, maxWidth: 320 }}
                >
                  <option value={-1}>Select your team...</option>
                  {sleeperTeams.map((t, i) => (
                    <option key={i} value={i}>
                      {t.name} ({(t.players || []).length} players, {(t.picks || []).length} picks)
                    </option>
                  ))}
                </select>
                {selectedTeamIdx >= 0 && sleeperTeams[selectedTeamIdx] && (
                  <span className="muted" style={{ fontSize: "0.72rem" }}>
                    Loaded {(sleeperTeams[selectedTeamIdx].players || []).length} players + {(sleeperTeams[selectedTeamIdx].picks || []).length} picks
                    {leagueRosters ? ` · ${leagueRosters.length} opponents` : ""}
                  </span>
                )}
              </div>
            )}

            <textarea
              className="input roster-textarea"
              placeholder="Enter roster (comma or newline separated): Josh Allen, Bijan Robinson, Ja'Marr Chase, ..."
              value={rosterInput}
              onChange={(e) => { setRosterInput(e.target.value); setSelectedTeamIdx(-1); setLeagueRosters(null); }}
              rows={3}
              style={{ width: "100%", resize: "vertical", fontFamily: "inherit" }}
            />

            <div className="row" style={{ marginTop: 8, alignItems: "center" }}>
              <button
                className="button"
                onClick={fetchSuggestions}
                disabled={suggestionsLoading}
                style={{ fontWeight: 700, borderColor: "var(--cyan)", color: "var(--cyan)" }}
              >
                {suggestionsLoading ? "Analyzing..." : "Get Suggestions"}
              </button>
              {suggestions && (
                <span className="muted" style={{ fontSize: "0.76rem" }}>
                  {suggestions.totalSuggestions} suggestions · {suggestions.metadata?.rosterMatched || 0}/{parseRoster().length} matched
                  {(suggestions.metadata?.opponentRostersAnalyzed || 0) > 0
                    ? ` · ${suggestions.metadata.opponentRostersAnalyzed} opponents analyzed`
                    : ""}
                </span>
              )}
            </div>

            {suggestionsError && (
              <p style={{ color: "var(--red)", fontSize: "0.82rem", margin: "8px 0 0" }}>{suggestionsError}</p>
            )}

            {/* Roster analysis summary */}
            {suggestions?.rosterAnalysis && (
              <div style={{ marginTop: 10, display: "flex", gap: 16, flexWrap: "wrap", fontSize: "0.78rem" }}>
                {suggestions.rosterAnalysis.surplusPositions.length > 0 && (
                  <span>
                    <span className="label">Can trade from </span>
                    <span style={{ color: "var(--green)", fontWeight: 600 }}>
                      {suggestions.rosterAnalysis.surplusPositions.join(", ")}
                    </span>
                  </span>
                )}
                {suggestions.rosterAnalysis.needPositions.length > 0 && (
                  <span>
                    <span className="label">Should target </span>
                    <span style={{ color: "var(--red)", fontWeight: 600 }}>
                      {suggestions.rosterAnalysis.needPositions.join(", ")}
                    </span>
                  </span>
                )}
                {suggestions.rosterAnalysis.surplusPositions.length === 0 &&
                 suggestions.rosterAnalysis.needPositions.length === 0 && (
                  <span className="muted">Roster is balanced — no clear surplus or need detected.</span>
                )}
              </div>
            )}

            {/* Category tabs */}
            {suggestions && suggestions.totalSuggestions > 0 && (
              <>
                <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
                  {SUGG_TYPES.map((t) => {
                    const count = suggestionCounts[t.key] || 0;
                    const isActive = suggestionTab === t.key;
                    const isEmpty = count === 0;
                    return (
                      <button
                        key={t.key}
                        className="button"
                        onClick={() => setSuggestionTab(t.key)}
                        style={{
                          fontSize: "0.76rem",
                          padding: "5px 10px",
                          borderColor: isActive ? "var(--cyan)" : "var(--border)",
                          color: isActive ? "var(--cyan)" : isEmpty ? "var(--border)" : "var(--muted)",
                          background: isActive ? "rgba(255, 199, 4,0.08)" : undefined,
                          opacity: isEmpty && !isActive ? 0.5 : 1,
                        }}
                      >
                        {t.label}{count > 0 ? ` (${count})` : ""}
                      </button>
                    );
                  })}
                </div>

                {/* Suggestion cards */}
                <div className="list" style={{ marginTop: 10 }}>
                  {(suggestions[suggestionTab] || []).map((s, i) => {
                    const eb = edgeBadge(s.edge);
                    const cb = confidenceBadge(s.confidence);
                    const rs = s.rankScore;
                    const isTopPick = i === 0 && rs && rs.total >= 12;
                    return (
                      <div
                        key={`${suggestionTab}-${i}`}
                        className="card"
                        style={{
                          padding: 10,
                          borderColor: isTopPick ? "rgba(52,211,153,0.5)" : s.edge ? "rgba(255, 199, 4,0.3)" : undefined,
                          borderWidth: isTopPick ? 2 : undefined,
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                          <div style={{ flex: 1 }}>
                            {/* Rank + Give / Get */}
                            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                              <span style={{
                                fontSize: "0.68rem", fontWeight: 700, color: i === 0 ? "var(--green)" : "var(--muted)",
                                minWidth: 18,
                              }}>#{i + 1}</span>
                              <div style={{ flex: 1 }}>
                                <div style={{ fontSize: "0.82rem" }}>
                                  <span style={{ color: "var(--red)", fontWeight: 600 }}>Give </span>
                                  {s.give.map((p, pi) => (
                                    <span key={pi}>
                                      {pi > 0 && <span className="muted"> + </span>}
                                      <span style={{ fontWeight: 600 }}>{p.name}</span>
                                      <span className="muted"> {p.position} {p.displayValue.toLocaleString()}</span>
                                    </span>
                                  ))}
                                </div>
                                <div style={{ fontSize: "0.82rem", marginTop: 3 }}>
                                  <span style={{ color: "var(--green)", fontWeight: 600 }}>Get </span>
                                  {s.receive.map((p, pi) => (
                                    <span key={pi}>
                                      {pi > 0 && <span className="muted"> + </span>}
                                      <span style={{ fontWeight: 600 }}>{p.name}</span>
                                      <span className="muted"> {p.position} {p.displayValue.toLocaleString()}</span>
                                    </span>
                                  ))}
                                </div>
                              </div>
                            </div>

                            {/* Badges row */}
                            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", marginLeft: 24 }}>
                              <span className="badge" style={{ color: fairnessColor(s.fairness), borderColor: fairnessColor(s.fairness) }}>
                                {fairnessLabel(s.fairness)}
                                {s.gap !== 0 && ` (${s.gap > 0 ? "+" : ""}${s.gap.toLocaleString()})`}
                              </span>
                              <span className="badge" style={{ color: cb.color, borderColor: cb.border, background: cb.bg }}>
                                {cb.label}
                              </span>
                              {s.strategy !== "neutral" && (
                                <span className="badge" style={{ textTransform: "capitalize" }}>
                                  {s.strategy === "contender" ? "Contender move" : "Rebuilder move"}
                                </span>
                              )}
                              {eb && (
                                <span className="badge" style={{ color: eb.color, background: eb.bg, borderColor: eb.color }}>
                                  {eb.text}
                                </span>
                              )}
                            </div>

                            {/* Rationale */}
                            <div style={{ marginLeft: 24 }}>
                              <div className="muted" style={{ fontSize: "0.74rem", marginTop: 5 }}>{s.rationale}</div>
                              {s.whyThisHelps && (
                                <div style={{ fontSize: "0.74rem", marginTop: 2, color: "var(--cyan)" }}>{s.whyThisHelps}</div>
                              )}
                              {s.edgeExplanation && (
                                <div style={{ fontSize: "0.72rem", marginTop: 2, fontStyle: "italic", color: "#fbbf24" }}>{s.edgeExplanation}</div>
                              )}

                              {/* Balancers */}
                              {s.suggestedBalancers?.length > 0 && (
                                <div className="muted" style={{ fontSize: "0.72rem", marginTop: 4 }}>
                                  To even it out, add: {s.suggestedBalancers.map((b) => `${b.name} (${b.displayValue.toLocaleString()})`).join(", ")}
                                </div>
                              )}

                              {/* Opponent fit */}
                              {s.opponentFit && (
                                <div style={{ fontSize: "0.72rem", marginTop: 3, color: "var(--cyan)" }}>
                                  {s.opponentFit}
                                </div>
                              )}

                              {/* Rank score transparency (collapsed by default) */}
                              {rs && (
                                <details style={{ marginTop: 4 }}>
                                  <summary className="muted" style={{ fontSize: "0.66rem", cursor: "pointer" }}>
                                    Why #{i + 1}? Score {rs.total}
                                  </summary>
                                  <div className="muted" style={{ fontSize: "0.66rem", marginTop: 2, lineHeight: 1.5 }}>
                                    Value {rs.base_value} + Fairness {rs.fairness} + Consensus {rs.confidence}
                                    {rs.need_severity > 0 && ` + Need ${rs.need_severity}`}
                                    {rs.edge > 0 && ` + Edge ${rs.edge}`}
                                    {rs.opponent_fit > 0 && ` + Partner ${rs.opponent_fit}`}
                                    {" "}= {rs.total}
                                  </div>
                                </details>
                              )}
                            </div>
                          </div>

                          {/* Apply button */}
                          <button
                            className="button"
                            style={{ fontSize: "0.72rem", padding: "4px 8px", whiteSpace: "nowrap" }}
                            onClick={() => applySuggestion(s)}
                          >
                            Load Trade
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  {(suggestions[suggestionTab] || []).length === 0 && (
                    <div className="muted" style={{ fontSize: "0.82rem", padding: "8px 0" }}>
                      {suggestionTab === "sellHigh"
                        ? "No sell-high opportunities found. You may not have enough depth at any position to move a piece."
                        : suggestionTab === "buyLow"
                        ? "No buy-low targets found. Your surplus positions may not have tradeable pieces in the right value range."
                        : suggestionTab === "consolidation"
                        ? "No consolidation trades found. This requires 2+ depth pieces that combine into a single upgrade."
                        : "No positional upgrades found. Your starters may already be top-tier, or no upgrade targets match your depth value."}
                    </div>
                  )}
                </div>
              </>
            )}

            {suggestions && suggestions.totalSuggestions === 0 && (
              <div style={{ marginTop: 12, padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8, fontSize: "0.82rem" }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>No trade suggestions found</div>
                <div className="muted" style={{ fontSize: "0.76rem", lineHeight: 1.5 }}>
                  {suggestions.metadata?.rosterMatched < 5
                    ? `Only ${suggestions.metadata?.rosterMatched || 0} of ${parseRoster().length} players matched our database. Check spelling or try adding more players.`
                    : suggestions.rosterAnalysis?.surplusPositions?.length === 0
                    ? "Your roster has no clear positional surplus. The engine needs at least one position with depth beyond starters to suggest trades."
                    : "Your roster appears well-balanced. No actionable trades met our quality threshold."}
                </div>
              </div>
            )}
          </div>

          {/* Sticky verdict tray (kept for scroll context, 2-team only) */}
          {sides.length === 2 && (
            <div className="trade-sticky-tray">
              <div className="trade-tray-main">
                <div>
                  <div className="label">Side A</div>
                  <div className="value" style={{ fontSize: "1.0rem" }}>{Math.round(pwTotalA).toLocaleString()}</div>
                </div>
                <div style={{ flex: 1, maxWidth: 220 }}>
                  {/* Verdict bar */}
                  <div style={{ position: "relative", height: 10, background: "var(--border)", borderRadius: 5, overflow: "hidden", margin: "6px 0" }}>
                    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to right, var(--green), transparent 40%, transparent 60%, var(--red))", opacity: 0.3, borderRadius: 5 }} />
                    <div style={{
                      position: "absolute", top: -1, width: 12, height: 12, borderRadius: "50%",
                      background: colorFromGap(pwGap) === "green" ? "var(--green)" : colorFromGap(pwGap) === "red" ? "var(--red)" : "var(--cyan)",
                      border: "2px solid var(--bg)", left: `calc(${verdictBarPosition(pwGap)}% - 6px)`, transition: "left 0.3s",
                    }} />
                  </div>
                  <div className={`verdict ${colorFromGap(pwGap)}`} style={{ textAlign: "center", fontSize: "0.82rem" }}>
                    {verdictFromGap(pwGap)}{pctGap > 0 ? ` (${pctGap}%)` : ""}
                  </div>
                  <div className="muted" style={{ fontSize: "0.66rem", textAlign: "center" }}>
                    Gap {Math.round(pwGap).toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="label">Side B</div>
                  <div className="value" style={{ fontSize: "1.0rem" }}>{Math.round(pwTotalB).toLocaleString()}</div>
                </div>
              </div>
            </div>
          )}

          {/* Picker overlay */}
          {pickerOpen && (
            <div className="picker-overlay" onClick={() => setPickerOpen(false)}>
              <div className="picker-sheet" onClick={(e) => e.stopPropagation()}>
                <div className="picker-header">
                  <div style={{ minWidth: 0 }}>
                    <h3 style={{ margin: 0 }}>Add to Side {sides[activeSide]?.label || "?"}</h3>
                    <p className="muted picker-subtitle">Tap a player/pick to add instantly.</p>
                  </div>
                  <button className="picker-close" onClick={() => setPickerOpen(false)} aria-label="Close picker">&times;</button>
                </div>
                <div className="picker-search-row">
                  <input
                    ref={pickerInputRef}
                    className="input"
                    placeholder="Search player or pick..."
                    value={pickerQuery}
                    onChange={(e) => setPickerQuery(e.target.value)}
                    style={{ flex: 1 }}
                  />
                  <select className="select" value={pickerFilter} onChange={(e) => setPickerFilter(e.target.value)}>
                    <option value="all">All</option>
                    <option value="offense">OFF</option>
                    {idpEnabled && <option value="idp">IDP</option>}
                    <option value="pick">Picks</option>
                  </select>
                </div>
                {!pickerQuery && recentRows.length > 0 && (
                  <div className="picker-recent">
                    <div className="label" style={{ marginBottom: 6 }}>Recent</div>
                    <div className="list">
                      {recentRows.slice(0, 8).map((r) => (
                        <button key={`recent-${r.name}`} className="asset-row button-reset" onClick={() => addToActiveSide(r)}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                            <PlayerImage
                              playerId={r.raw?.playerId}
                              team={r.team}
                              position={r.pos}
                              name={r.name}
                              size={24}
                            />
                            <div style={{ minWidth: 0 }}>
                              <div className="asset-name">{r.name}</div>
                              <div className="asset-meta">{r.pos} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
                            </div>
                          </div>
                          <span className="badge">Add</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="picker-table-wrap">
                  <table style={{ width: "100%", fontSize: "0.78rem" }}>
                    <thead>
                      <tr>
                        {[
                          { col: "rank", label: "Rank", className: "picker-rank-col", style: { width: 55, textAlign: "center" } },
                          { col: "name", label: "Player" },
                          { col: "pos", label: "Pos", style: { width: 46 } },
                          { col: "value", label: "Value", style: { width: 70, textAlign: "right" } },
                          ...RANKING_SOURCES.map((src) => ({
                            col: `src:${src.key}`,
                            label: src.columnLabel,
                            className: "picker-source-col",
                            style: { width: 65, textAlign: "right" },
                          })),
                        ].map(({ col, label, style, className }) => (
                          <th key={col} className={className || undefined} style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", ...style }}
                            onClick={() => {
                              if (pickerSortCol === col) setPickerSortAsc((p) => !p);
                              else { setPickerSortCol(col); setPickerSortAsc(["rank", "name", "pos"].includes(col)); }
                            }}>
                            {label}{pickerSortCol === col ? (pickerSortAsc ? " \u25B2" : " \u25BC") : ""}
                          </th>
                        ))}
                        <th className="picker-add-col" style={{ width: 40 }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {pickerRows.map((r) => (
                        <tr key={`pick-${r.name}`} className="picker-row" onClick={() => addToActiveSide(r)}>
                          <td className="picker-rank-col" style={{ textAlign: "center", fontFamily: "var(--mono, monospace)", fontWeight: 600, color: "var(--cyan)" }}>
                            {r.blendedSourceRank != null ? r.blendedSourceRank.toFixed(1) : "\u2014"}
                          </td>
                          <td style={{ fontWeight: 600 }}>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              <PlayerImage
                                playerId={r.raw?.playerId}
                                team={r.team}
                                position={r.pos}
                                name={r.name}
                                size={22}
                              />
                              {r.name}
                            </span>
                          </td>
                          <td><span className={posBadgeClass(r)}>{r.pos}</span></td>
                          <td style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontWeight: 600 }}>
                            {Math.round(displayValue(r, settings)).toLocaleString()}
                          </td>
                          {RANKING_SOURCES.map((src) => {
                            const raw = r.canonicalSites?.[src.key];
                            const hasVal = raw != null && Number.isFinite(Number(raw));
                            return (
                              <td key={src.key} className="picker-source-col" style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontSize: "0.74rem" }}>
                                {hasVal ? Math.round(Number(raw)).toLocaleString() : "\u2014"}
                              </td>
                            );
                          })}
                          <td className="picker-add-col"><span className="badge" style={{ fontSize: "0.6rem" }}>Add</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {pickerRows.length === 0 && <div className="muted" style={{ padding: 8 }}>No assets match.</div>}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

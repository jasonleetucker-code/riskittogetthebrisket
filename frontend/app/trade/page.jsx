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
  getPlayerEdge,
  findBalancers,
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
import { useApp } from "@/components/AppShell";
import { posBadgeClass } from "@/lib/display-helpers";

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

function fairnessLabel(f) {
  if (f === "even") return "Even value";
  if (f === "lean") return "Slight lean";
  return "Stretch";
}

function confidenceBadge(c) {
  if (c === "high") return { label: "High consensus", bg: "rgba(52,211,153,0.15)", border: "rgba(52,211,153,0.4)", color: "var(--green)" };
  if (c === "medium") return { label: "Moderate consensus", bg: "rgba(255,198,47,0.12)", border: "rgba(255,198,47,0.35)", color: "var(--cyan)" };
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
        const averageCovered = (meta, sourceList) => {
          let sumVc = 0;
          let covered = 0;
          for (const sub of sourceList) {
            const vc = Number(meta[sub.key]?.valueContribution);
            if (Number.isFinite(vc) && vc > 0) {
              sumVc += vc;
              covered += 1;
            }
          }
          return covered > 0 ? sumVc / covered : 0;
        };
        const sideValues = assetsBySide.map((assets) =>
          assets.map((row) => {
            if (!includePicks && row.pos === "PICK") return 0;
            const meta = row.sourceRankMeta || {};
            const mainAvg = averageCovered(meta, mainSubs);
            if (mainAvg > 0) return mainAvg;
            return averageCovered(meta, rookieSubs);
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
    <div className="card" style={{ marginTop: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
        <h3 style={{ margin: 0, fontSize: "0.88rem" }}>Per-source winner</h3>
        <span className="muted" style={{ fontSize: "0.72rem" }}>
          VA-adjusted totals on the 0-9999 value scale, summed per vendor. Sub-boards (e.g. DLF SF + DLF RK) roll up into one row; margin shows winner's edge as a percent.
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
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

  // Legacy 2-team gap computations (for sticky tray + 2-team balancers)
  const pwTotalA = sideTotals[0]?.adjusted || 0;
  const pwTotalB = sideTotals[1]?.adjusted || 0;
  const linTotalA = sideTotals[0]?.raw || 0;
  const linTotalB = sideTotals[1]?.raw || 0;
  const pwGap = pwTotalA - pwTotalB;
  const pctGap = Math.max(pwTotalA, pwTotalB) > 0 ? Math.round(Math.abs(pwGap) / Math.max(pwTotalA, pwTotalB) * 100) : 0;

  // Balancing suggestions (2-team mode only)
  const balancers = useMemo(() => {
    if (sides.length !== 2) return [];
    if (Math.abs(pwGap) < 350) return [];
    const allInTrade = new Set(sides.flatMap((s) => s.assets.map((a) => a.name)));
    const available = rows.filter((r) => !allInTrade.has(r.name));
    return findBalancers(pwGap, available, valueMode);
  }, [pwGap, rows, sides, valueMode]);

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
    const available = rows.filter((r) => !allInTrade.has(r.name));
    const suggestions = findBalancers(gap, available, valueMode);
    return {
      overpayingIdx: worstIdx,
      underpayingIdx: bestIdx, // panel rendered on the side that needs to give more
      gap,
      suggestions,
    };
  }, [sides, sideFlows, rows, valueMode]);

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
          va = a.rankDerivedValue || a.values?.full || 0; vb = b.rankDerivedValue || b.values?.full || 0;
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
      // covers the common case.  For near-matches we punt and
      // surface the entry as unmatched so the user knows to add it
      // manually rather than silently dropping it.
      const resolveBatch = (entries) => {
        const found = [];
        const missing = [];
        for (const entry of entries) {
          const row = rowByName.get(entry.name);
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
      const res = await fetch("/api/trade/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(leagueRosters ? { roster, league_rosters: leagueRosters } : { roster }),
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
          </div>

          {ktcImportOpen && (
            <div
              className="card"
              style={{
                marginBottom: 10,
                padding: "10px 12px",
                border: "1px solid var(--cyan)",
                background: "rgba(255,198,47,0.04)",
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

              return (
                <div className="card" key={side.id} style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <h3 style={{ margin: 0 }}>Side {side.label}</h3>
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
                          <div>
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
                                <div>
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
                  {sides.length === 2 && isUnderpaying && balancers.length > 0 && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(255,198,47,0.06)", borderRadius: 6 }}>
                      <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>To balance, consider adding:</div>
                      {balancers.map((b) => (
                        <button key={b.name} className="button-reset muted" style={{ display: "block", fontSize: "0.72rem", cursor: "pointer" }}
                          onClick={() => { const row = rowByName.get(b.name); if (row) addToSide(row, sideIdx); }}>
                          {b.name} ({b.pos}) · {b.value.toLocaleString()}
                        </button>
                      ))}
                    </div>
                  )}
                  {/* Balancers (3+ team mode) - show on the side getting the best deal */}
                  {multiBalancers && sideIdx === multiBalancers.underpayingIdx && multiBalancers.suggestions.length > 0 && (
                    <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(255,198,47,0.06)", borderRadius: 6 }}>
                      <div className="label" style={{ fontSize: "0.68rem", marginBottom: 4 }}>
                        To balance (Side {sides[multiBalancers.overpayingIdx]?.label} loses {Math.round(multiBalancers.gap).toLocaleString()}):
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
                          background: isActive ? "rgba(255,198,47,0.08)" : undefined,
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
                          borderColor: isTopPick ? "rgba(52,211,153,0.5)" : s.edge ? "rgba(255,198,47,0.3)" : undefined,
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
                    <option value="idp">IDP</option>
                    <option value="pick">Picks</option>
                  </select>
                </div>
                {!pickerQuery && recentRows.length > 0 && (
                  <div className="picker-recent">
                    <div className="label" style={{ marginBottom: 6 }}>Recent</div>
                    <div className="list">
                      {recentRows.slice(0, 8).map((r) => (
                        <button key={`recent-${r.name}`} className="asset-row button-reset" onClick={() => addToActiveSide(r)}>
                          <div>
                            <div className="asset-name">{r.name}</div>
                            <div className="asset-meta">{r.pos} · {Math.round(effectiveValue(r, valueMode, settings)).toLocaleString()}</div>
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
                          <td style={{ fontWeight: 600 }}>{r.name}</td>
                          <td><span className={posBadgeClass(r)}>{r.pos}</span></td>
                          <td style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontWeight: 600 }}>
                            {Math.round(r.rankDerivedValue || r.values?.full || 0).toLocaleString()}
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

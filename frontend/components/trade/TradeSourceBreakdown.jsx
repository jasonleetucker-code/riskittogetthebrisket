"use client";

/**
 * TradeSourceBreakdown — per-vendor winner table.  Extracted from
 * frontend/app/trade/page.jsx (commit 2026-04-30) so /trade,
 * /waivers, and any future N-side comparison surface can render
 * the identical breakdown without duplicating the V13 Value
 * Adjustment math.
 *
 * Inputs:
 *   - ``sides``: array of ``{label, assets}`` (length 2+; 2 is the
 *     waiver case, 3+ is the multi-team trade case).
 *   - ``settings``: kept as a memo dep so the component re-runs
 *     when source weights / overrides change; the math itself
 *     reads from ``RANKING_SOURCES`` registry directly.
 *
 * The component walks ``RANKING_SOURCES`` grouped by vendor (KTC
 * TE+, DLF, Flock, …), computes per-vendor side totals using
 * ``sourceRankMeta[key].valueContribution`` (or raw KTC values
 * for the V13-calibrated KTC vendor), applies VA via
 * ``valueAdjustmentFromSideArrays``, and renders a row per vendor
 * with each side's value, the winner, and the margin %.
 *
 * Empty-rows diagnostic copy is preserved: when no vendor covers
 * the trade, render the card chrome so users know the section is
 * wired up — distinguishes "stale cache / bundle missing" from
 * "data path missing per-source stamps."
 */

import { useMemo } from "react";

import {
  RANKING_SOURCES,
  SOURCE_VENDOR_LABELS,
  vendorForSource,
} from "@/lib/dynasty-data";
import { valueAdjustmentFromSideArrays } from "@/lib/trade-logic";

const KTC_RAW_NATIVE_VENDORS = new Set(["ktcSfTep"]);

export default function TradeSourceBreakdown({ sides, settings }) {
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
        // For KTC's TE+ board, the V13 Value Adjustment formula and
        // its empirical suppression thresholds (V13_SUPPRESS_RAW_DIFF,
        // V13_SUPPRESS_SAME_SIDE_RAW_DIFF) were calibrated against
        // KTC's raw 0-9999 piece values.  Feeding the formula the
        // canonical Hill-blended ``valueContribution`` instead would
        // mis-fire VA — sometimes suppressing a real VA, sometimes
        // inventing one — and the per-source KTC row would disagree
        // with what keeptradecut.com displays for the same trade.
        // We therefore use the raw KTC value from
        // ``row.canonicalSites['ktcSfTep']`` as the formula input.
        //
        // For every other vendor we keep the Hill-normalized
        // ``valueContribution``: rank-only sources don't have a raw
        // native value, and cross-market rank sources stash a
        // synthetic 100,000+ rank-encoded number in ``canonicalSites``
        // that would break the V13 formula's 0-9999-scaled ratios.
        const useRawNative = KTC_RAW_NATIVE_VENDORS.has(vendor);
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
        // Per-piece value resolution.  Both players and picks go
        // through ``averageCovered`` which returns 0 for any sub-
        // board that doesn't rank this piece — so a vendor with no
        // pick coverage naturally contributes 0 for that pick.  The
        // previous behaviour hard-coded picks to KTC-only, which
        // zeroed IDPTC's real pick coverage (it does rank picks)
        // and turned 1v2 trades into 1v1 from IDPTC's perspective,
        // tripping the 1v1 VA suppression in ``ktcAdjustPackage``.
        const sideValues = assetsBySide.map((assets) =>
          assets.map((row) => {
            const mainAvg = averageCovered(row, mainSubs);
            if (mainAvg > 0) return mainAvg;
            return averageCovered(row, rookieSubs);
          }),
        );
        const rawTotals = sideValues.map((vs) =>
          vs.reduce((sum, v) => sum + v, 0),
        );
        const coverage = sideValues.map(
          (vs) => vs.filter((v) => v > 0).length,
        );
        // Skip vendors that touch zero pieces across the whole trade.
        if (coverage.reduce((a, b) => a + b, 0) === 0) return null;

        const adjustments = valueAdjustmentFromSideArrays(sideValues);
        const adjustedTotals = rawTotals.map(
          (t, i) => t + (adjustments[i] || 0),
        );

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
    // ``settings`` is kept in the dep list for memo invalidation
    // when source weights / overrides change downstream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sides, settings]);

  // Empty-rows diagnostic — historically this branch returned null,
  // which made it impossible to distinguish "card not rendering at
  // all" (the iOS-PWA-stale-cache symptom) from "card rendering but
  // no per-vendor coverage" (a data path symptom).  We now render
  // the card chrome even when rows is empty so users can SEE the
  // section is wired up, and ops can grep the rendered DOM for the
  // diagnostic copy below to confirm the bundle shipped.  Cheap
  // (one extra .card on a page with ~20 already) and self-documenting.
  const hasRows = rows.length > 0;
  const sideLabels = sides.map((s) => s.label);

  return (
    <div className="card source-breakdown-card" style={{ marginTop: 14 }}>
      <div className="source-breakdown-header">
        <span className="source-breakdown-header-text">
          <span
            className="source-breakdown-title"
            style={{ margin: 0, fontSize: "0.88rem", fontWeight: 700 }}
          >
            Per-source winner
          </span>
          <span
            className="muted source-breakdown-subtitle"
            style={{ fontSize: "0.72rem" }}
          >
            VA-adjusted totals on the 0-9999 value scale, summed per vendor.
            Sub-boards (e.g. DLF SF + DLF RK) roll up into one row; margin
            shows winner's edge as a percent.
          </span>
        </span>
      </div>
      {!hasRows && (
        <div
          className="muted"
          style={{ padding: "10px 0", fontSize: "0.78rem", lineHeight: 1.45 }}
        >
          No vendor coverage for this trade yet — add at least one player to
          each side and the per-source breakdown will fill in.  If both sides
          are populated and you still see this, the contract may be missing
          per-source value stamps for those rows; check{" "}
          <code style={{ fontSize: "0.72rem" }}>row.sourceRankMeta</code> in
          DevTools.
        </div>
      )}
      {hasRows && (
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
                    {row.winnerIdx === null
                      ? "Even"
                      : `Side ${row.winnerLabel}`}
                  </td>
                  <td
                    style={{
                      textAlign: "right",
                      fontFamily: "var(--mono)",
                      color:
                        row.winnerIdx === null
                          ? "var(--muted)"
                          : "var(--text)",
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
      )}
    </div>
  );
}

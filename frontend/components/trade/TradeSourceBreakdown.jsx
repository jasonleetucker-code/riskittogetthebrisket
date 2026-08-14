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

import { useMemo, useState } from "react";

import {
  RANKING_SOURCES,
  SOURCE_VENDOR_LABELS,
  vendorForSource,
} from "@/lib/dynasty-data";
import { valueAdjustmentFromSideArrays } from "@/lib/trade-logic";
import { resolveVendorAssetValue, summariseSide } from "@/lib/second-opinions";

const KTC_RAW_NATIVE_VENDORS = new Set(["ktcSfTep"]);

// NOTE: this component deliberately takes NO ``valueMode``.
//
// It used to, and passed it to ``effectiveValue`` for the
// uncovered-asset fallback — so flipping the Trade Calculator's
// display toggle to "Raw" swapped the fallback onto the legacy scraper
// composite while every vendor number beside it stayed canonical.
// Measured: rawComposite/canonical runs 0.266-2.082 across 805 rows.
// A user's diagnostic selection may not change the unit system the
// arithmetic runs in, so the basis is owned by
// ``lib/second-opinions.js`` and nothing here can override it.
export default function TradeSourceBreakdown({ sides, settings }) {
  // When ON (default), pieces a vendor does not cover are filled with
  // our CANONICAL value — explicitly, via ``resolveVendorAssetValue``,
  // never through a display mode.  Imputed cells get an italic style +
  // dotted underline + tooltip.  Toggle OFF for strict "what does this
  // vendor literally say" mode, which now reports the uncovered pieces
  // as unresolved rather than summing them as zeros.
  const [imputeUncovered, setImputeUncovered] = useState(true);

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
        // Per-asset value resolution lives in ``lib/second-opinions.js``,
        // which returns a BASIS with every number and refuses to return a
        // quantity it cannot justify.  KTC is the one vendor whose covered
        // assets use its own native values (V13 VA was calibrated on
        // them), and it is therefore the one vendor we will not impute
        // into — canonical and KTC-native are not interchangeable
        // (median ratio 1.091, drifting 0.947 at the top of the board to
        // 1.142 in the tail, range 0.400-1.491).
        const useRawNative = KTC_RAW_NATIVE_VENDORS.has(vendor);
        const sideSummaries = assetsBySide.map((assets) =>
          summariseSide(
            assets.map((row) =>
              resolveVendorAssetValue({
                row,
                mainSubs,
                rookieSubs,
                useKtcNative: useRawNative,
                impute: imputeUncovered,
              }),
            ),
          ),
        );
        const sideValues = sideSummaries.map((s) => s.values);
        const imputedCounts = sideSummaries.map((s) => s.imputed);
        const nativeCounts = sideSummaries.map((s) => s.native);
        const unresolvedCounts = sideSummaries.map((s) => s.unresolved);
        const incomplete = sideSummaries.some((s) => s.incomplete);
        const rawTotals = sideValues.map((vs) =>
          vs.reduce((sum, v) => sum + v, 0),
        );
        const coverage = nativeCounts.map((n, i) => n + imputedCounts[i]);
        // Skip vendors that touch zero pieces across the whole trade
        // (this can still happen when imputation is OFF and the
        // vendor covers nothing — keep the empty-rows diagnostic
        // path useful).
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
        const marginPct = winnerTotal > 0 ? (rawMargin / winnerTotal) * 100 : 0;
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
          imputedCounts,
          nativeCounts,
          unresolvedCounts,
          incomplete,
          winnerIdx: tied ? null : winnerIdx,
          winnerLabel: tied ? "Even" : sides[winnerIdx]?.label || "?",
          marginPct,
        };
      })
      .filter(Boolean);
    // ``settings`` is kept in the dep list for memo invalidation
    // when source weights / overrides change downstream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sides, settings, imputeUncovered]);

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
            Sub-boards (e.g. DLF SF + DLF RK) roll up into one row; margin shows
            winner's edge as a percent.
          </span>
        </span>
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: "0.72rem",
            color: "var(--muted, #c7b8dc)",
            cursor: "pointer",
            userSelect: "none",
            marginLeft: "auto",
          }}
          title="When ON: vendors that don't rank a piece (e.g. DLF on picks) get our blended value as a stand-in so side totals are comparable across rows.  Imputed cells render in italic.  Toggle OFF for strict 'what does this vendor literally say' mode."
        >
          <input
            type="checkbox"
            checked={imputeUncovered}
            onChange={(e) => setImputeUncovered(e.target.checked)}
          />
          <span>Fill uncovered pieces with our value</span>
        </label>
      </div>
      {!hasRows && (
        <div
          className="muted"
          style={{ padding: "10px 0", fontSize: "0.78rem", lineHeight: 1.45 }}
        >
          No per-source coverage for this trade yet — add at least one player to
          each side and the breakdown will fill in. If both sides already have
          players, none of them carry per-source values on the current board,
          which usually means they sit outside the sources&apos; published
          range.
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
                    const imputedN = row.imputedCounts?.[i] || 0;
                    const titleParts = [];
                    titleParts.push(
                      `raw ${Math.round(row.rawTotals[i]).toLocaleString()}`,
                    );
                    if (hasAdj) {
                      titleParts.push(
                        `+ VA ${Math.round(row.adjustments[i]).toLocaleString()}`,
                      );
                    }
                    if (imputedN > 0) {
                      titleParts.push(
                        `${imputedN} piece${imputedN === 1 ? "" : "s"} imputed with our value (vendor doesn't rank ${imputedN === 1 ? "it" : "them"})`,
                      );
                    }
                    return (
                      <td
                        key={`v-${row.key}-${i}`}
                        style={{
                          textAlign: "right",
                          fontFamily: "var(--mono)",
                          opacity: row.coverage[i] === 0 ? 0.35 : 1,
                          fontWeight: row.winnerIdx === i ? 700 : 400,
                          fontStyle: imputedN > 0 ? "italic" : "normal",
                          textDecoration:
                            imputedN > 0 ? "underline dotted" : "none",
                          textUnderlineOffset: imputedN > 0 ? 2 : undefined,
                          textDecorationColor:
                            imputedN > 0 ? "var(--muted, #c7b8dc)" : undefined,
                        }}
                        title={titleParts.join(" ")}
                      >
                        {Math.round(total).toLocaleString()}
                        {hasAdj && (
                          <span
                            style={{
                              color: "var(--cyan)",
                              fontSize: "0.68rem",
                              marginLeft: 4,
                              fontStyle: "normal",
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
                    {row.incomplete
                      ? "Incomplete"
                      : row.winnerIdx === null
                        ? "Even"
                        : `Side ${row.winnerLabel}`}
                  </td>
                  <td
                    style={{
                      textAlign: "right",
                      fontFamily: "var(--mono)",
                      color:
                        row.winnerIdx === null ? "var(--muted)" : "var(--text)",
                    }}
                  >
                    {row.incomplete || row.winnerIdx === null
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

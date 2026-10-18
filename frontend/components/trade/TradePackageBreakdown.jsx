"use client";

/**
 * TradePackageBreakdown — how each package is built (TC-B2, Value tab of
 * /trade's Supporting intelligence):
 *
 *   - TCM-M01  one stacked bar per side: each line's raw canonical value, then
 *              the side's Value Adjustment as its own, visibly different
 *              segment; every number is printed in the legend, not chart-only;
 *   - TCM-M02  one presentation identity per line across the bars and the
 *              legend (a marker number + the fixed chart series);
 *   - TCM-M04  Quick Trade Facts per side;
 *   - TCM-M05  value concentration (largest piece's share, inverse
 *              Herfindahl "behaves like N equal pieces"), with no better/worse
 *              reading.
 *
 * Display only.  Values are `effectiveValue` (what the side totals sum), the
 * VA is the page's `sideTotals[i].adjustment`, ranks are backend stamps
 * (lib/trade-package-facts.js).  It never grades the trade: the package band
 * is the meter's and the decision is the War Room's.
 */

import { useMemo } from "react";
import { DataTable } from "@/components/ds";
import {
  sidePackageFacts,
  sideValueSegments,
  tradeAssetIdentities,
  valueConcentration,
} from "@/lib/trade-package-facts";
import styles from "./trade-package-breakdown.module.css";

const n0 = (v) => Math.round(Number(v)).toLocaleString();
const pct = (v) => `${Math.round(Number(v) * 100)}%`;

function swatchStyle(seg) {
  if (seg.kind === "va") return undefined;
  return { background: seg.series ? `var(--chart-${seg.series})` : "var(--neutral-signal)" };
}

function barSummary(label, segments, adjusted) {
  const parts = segments
    .filter((s) => s.value != null)
    .map((s) =>
      s.kind === "va"
        ? `Value Adjustment ${n0(s.value)}`
        : `${s.marker}. ${s.label}${s.count > 1 ? ` ×${s.count}` : ""} ${n0(s.value)}`,
    );
  return `${label}: ${parts.join(", ")}; adjusted total ${n0(adjusted)}`;
}

function SideBar({ side, segments, adjusted, scale }) {
  const label = `Side ${side.label}`;
  return (
    <div className={styles.barRow} data-testid={`package-bar-${side.label}`}>
      <span className={styles.barLabel}>{label}</span>
      <div className={styles.bar} role="img" aria-label={barSummary(label, segments, adjusted)}>
        {segments
          .filter((s) => s.value != null && s.value > 0)
          .map((s) => (
            <span
              key={s.key}
              className={s.kind === "va" ? `${styles.segment} ${styles.segmentVa}` : styles.segment}
              data-segment={s.kind === "va" ? "va" : s.marker}
              style={{ width: `${(s.value / scale) * 100}%`, ...swatchStyle(s) }}
              title={`${s.kind === "va" ? s.label : `${s.marker}. ${s.label}`}: ${n0(s.value)}`}
            />
          ))}
      </div>
      <span className={styles.barTotal}>{n0(adjusted)}</span>
    </div>
  );
}

function Legend({ side, segments }) {
  return (
    <div className={styles.legendSide}>
      <span className={styles.legendTitle}>Side {side.label} sends</span>
      <ul className={styles.legend}>
        {segments.map((s) => (
          <li key={s.key} className={styles.legendItem}>
            <span
              className={s.kind === "va" ? `${styles.swatch} ${styles.segmentVa}` : styles.swatch}
              style={swatchStyle(s)}
              aria-hidden="true"
            />
            <span className={styles.legendName}>
              {s.kind === "va" ? (
                "Value Adjustment"
              ) : (
                <>
                  <span className={styles.marker}>{s.marker}.</span> {s.label}
                  {s.count > 1 ? ` ×${s.count}` : ""}
                </>
              )}
            </span>
            <span className={styles.legendValue}>
              {s.value == null ? "not priced" : s.kind === "va" ? `+${n0(s.value)}` : n0(s.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One facts row; `cell(facts, i)` returns the display string for side i. */
function factsRows(sides, facts, concentration) {
  const coverage = (n, of) => (of > 0 && n < of ? ` (${n} of ${of})` : "");
  const row = (id, measure, cell) => {
    const out = { id, measure };
    sides.forEach((s, i) => {
      out[`s${i}`] = cell(facts[i], i);
    });
    return out;
  };
  return [
    row("raw", "Raw value (priced pieces)", (f) => (f.pricedPieces ? n0(f.rawPriced) : "—")),
    row("pieces", "Pieces", (f) => String(f.pieces)),
    row("mix", "Players · picks", (f) => `${f.players} · ${f.picks}`),
    row("avgValue", "Average piece value", (f) =>
      f.averageValue == null ? "—" : `${n0(f.averageValue)}${coverage(f.pricedPieces, f.pieces)}`,
    ),
    row("avgAge", "Average player age", (f) =>
      f.averageAge == null
        ? "—"
        : `${f.averageAge.toFixed(1)}${coverage(f.agedPlayers, f.players)}`,
    ),
    row("avgRank", "Average consensus rank", (f) =>
      f.averageRank == null
        ? "—"
        : `${f.averageRank.toFixed(1)}${coverage(f.rankedPieces, f.pieces)}`,
    ),
    row("top", "Largest piece's share", (_f, i) =>
      concentration[i] ? pct(concentration[i].topShare) : "—",
    ),
    row("effective", "Behaves like (equal pieces)", (_f, i) =>
      concentration[i] ? concentration[i].effectiveCount.toFixed(1) : "—",
    ),
    row("unpriced", "Not priced", (f) => (f.unpriced.length ? f.unpriced.join(", ") : "none")),
  ];
}

export default function TradePackageBreakdown({ sides, sideTotals, valueMode }) {
  const model = useMemo(() => {
    const identities = tradeAssetIdentities(sides);
    const perSide = sides.map((side, i) => ({
      side,
      segments: sideValueSegments(
        side.assets,
        sideTotals?.[i]?.adjustment,
        valueMode,
        identities,
      ),
      adjusted: Number(sideTotals?.[i]?.adjusted) || 0,
      facts: sidePackageFacts(side.assets, valueMode),
      concentration: valueConcentration(side.assets, valueMode),
    }));
    // One scale for every bar: the largest drawn total, so bar lengths compare.
    const scale = Math.max(
      1,
      ...perSide.map((p) =>
        p.segments.reduce((sum, s) => sum + (s.value != null && s.value > 0 ? s.value : 0), 0),
      ),
    );
    return { perSide, scale };
  }, [sides, sideTotals, valueMode]);

  if (!sides.some((s) => (s.assets || []).length)) {
    return <p className={styles.note}>Add assets to see how each package is built.</p>;
  }

  const columns = [
    { key: "measure", header: "Fact" },
    ...sides.map((s, i) => ({ key: `s${i}`, header: `Side ${s.label}`, numeric: true })),
  ];
  const rows = factsRows(
    sides,
    model.perSide.map((p) => p.facts),
    model.perSide.map((p) => p.concentration),
  );

  return (
    <section className={styles.breakdown} aria-labelledby="package-breakdown-title" data-testid="package-breakdown">
      <h3 id="package-breakdown-title" className={styles.title}>
        Package breakdown
      </h3>
      <p className={styles.note}>
        Each bar is what that side sends: every asset&apos;s raw canonical value, then the side&apos;s
        Value Adjustment (hatched). All bars share one scale.
      </p>
      <div className={styles.bars}>
        {model.perSide.map((p) => (
          <SideBar
            key={p.side.id ?? p.side.label}
            side={p.side}
            segments={p.segments}
            adjusted={p.adjusted}
            scale={model.scale}
          />
        ))}
      </div>
      <div className={styles.legends}>
        {model.perSide.map((p) => (
          <Legend key={p.side.id ?? p.side.label} side={p.side} segments={p.segments} />
        ))}
      </div>
      <h3 className={styles.title}>Quick trade facts</h3>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey="id"
        caption="Quick trade facts per side"
        density="compact"
      />
      <p className={styles.note} data-testid="package-concentration-note">
        Concentration describes how a package is built — one large piece or many smaller ones. It is
        not better or worse on its own. Averages skip what does not apply (unpriced pieces, picks
        for age, unranked pieces) and say how many pieces they cover.
      </p>
    </section>
  );
}

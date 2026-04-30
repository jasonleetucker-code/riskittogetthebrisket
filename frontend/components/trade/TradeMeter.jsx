"use client";

/**
 * TradeMeter — fairness visualizer for any 2-side or N-side
 * value comparison.  Extracted from frontend/app/trade/page.jsx
 * (commit 2026-04-30) so both /trade and /waivers can render the
 * identical fairness bar against any pair of sides.
 *
 * Behavior + DOM are bit-identical to the original.  Code lifted
 * verbatim, including comments — the only change is moving from
 * inline functions to a default-exported component file so other
 * surfaces can import without duplicating the math.
 *
 * Dependencies (kept identical):
 *   - meterVerdict, percentageGap from lib/trade-logic
 *   - MonteCarloButton from components/ui
 *   - ResilientSection from components/ResilientSection
 */

import { meterVerdict, percentageGap } from "@/lib/trade-logic";
import { MonteCarloButton } from "@/components/ui";
import ResilientSection from "@/components/ResilientSection";

export default function TradeMeter({ sides, sideTotals, flows }) {
  const sideCount = sides.length;
  if (sideCount === 2) {
    return <TradeMeterTwoTeam sides={sides} sideTotals={sideTotals} />;
  }
  return (
    <TradeMeterMultiTeam sides={sides} sideTotals={sideTotals} flows={flows} />
  );
}

export function TradeMeterTwoTeam({ sides, sideTotals }) {
  const pwA = sideTotals[0]?.adjusted || 0;
  const pwB = sideTotals[1]?.adjusted || 0;
  const gap = pwA - pwB;
  const absGap = Math.abs(gap);
  const pctGap = percentageGap(pwA, pwB);
  const verdict = meterVerdict(absGap);
  const total = pwA + pwB;

  // Fill percentages for the bar
  const shareA = total > 0 ? (pwA / total) * 100 : 50;
  const shareB = total > 0 ? (pwB / total) * 100 : 50;

  // Winner label.  Defaults match the trade page ("Side A wins…");
  // /waivers passes ``label="Drop"``/``"Add"`` so the copy reads
  // "Drop wins by N%" / "Add wins by N%" naturally.
  const labelA = sides[0]?.label
    ? `Side ${sides[0].label}`
    : "Side A";
  const labelB = sides[1]?.label
    ? `Side ${sides[1].label}`
    : "Side B";
  let winnerText = "Even";
  if (pctGap >= 3) {
    winnerText = gap > 0
      ? `${labelA} wins by ${pctGap}%`
      : `${labelB} wins by ${pctGap}%`;
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
        <span className="muted" style={{ fontSize: "0.66rem" }}>
          {sides[0]?.label ? `Side ${sides[0].label}` : "Side A"}
        </span>
        <span className="muted" style={{ fontSize: "0.66rem" }}>
          {sides[1]?.label ? `Side ${sides[1].label}` : "Side B"}
        </span>
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

export function TradeMeterMultiTeam({ sides, sideTotals, flows }) {
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

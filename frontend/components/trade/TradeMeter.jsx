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
 *   - meterVerdict (the ONE fairness-band owner, lib/fairness-bands.js),
 *     percentageGap from lib/trade-logic
 *   - MonteCarloButton from components/ui
 *   - ResilientSection from components/ResilientSection
 */

import {
  TRADE_EVAL_STATE,
  meterVerdict,
  multiTeamNetSummary,
  percentageGap,
  tradeEvaluationState,
  withheldAssetsBySide,
  withheldReasonText,
} from "@/lib/trade-logic";
import { MonteCarloButton } from "@/components/ui";
import ResilientSection from "@/components/ResilientSection";

/** The meter's "nothing to compare yet" state — never a band (UX audit P0-6). */
export function TradeMeterEmpty() {
  return (
    <div className="trade-meter" data-trade-state={TRADE_EVAL_STATE.EMPTY}>
      <p className="muted" style={{ margin: 0 }}>
        Add assets to compare the packages. No verdict until there is a trade.
      </p>
    </div>
  );
}

/**
 * "Incomplete — no verdict" (TC-A, MISSING IS NEVER ZERO).  An unpriced asset
 * adds 0 to a side's total as an arithmetic neutral; a band, a share bar or a
 * "% more" computed over that 0 would grade a trade nobody has valued.
 */
export function TradeMeterIncomplete({ unpriced, sides }) {
  const names = (unpriced || [])
    .map((u) => `${u.name} (Side ${sides?.[u.side]?.label || "ABCDE"[u.side] || "?"})`)
    .join(", ");
  return (
    <div className="trade-meter-bottom" data-trade-state={TRADE_EVAL_STATE.INCOMPLETE}>
      <span className="trade-meter-verdict">INCOMPLETE</span>
      <span className="trade-meter-pct">
        No verdict: {unpriced.length} unpriced asset{unpriced.length === 1 ? "" : "s"} —{" "}
        {names}. Unknown is not worth 0; type a value on the row to price it.
      </span>
    </div>
  );
}

export default function TradeMeter({
  sides,
  sideTotals,
  flows,
  sidesSend = false,
  finalBySide = null,
}) {
  const sideCount = sides.length;
  if (tradeEvaluationState(sides).state === TRADE_EVAL_STATE.EMPTY) {
    return <TradeMeterEmpty />;
  }
  if (sideCount === 2) {
    return <TradeMeterTwoTeam sides={sides} sideTotals={sideTotals} sidesSend={sidesSend} />;
  }
  return (
    <TradeMeterMultiTeam
      sides={sides}
      sideTotals={sideTotals}
      flows={flows}
      finalBySide={finalBySide}
    />
  );
}

/**
 * `sidesSend` — each side lists what that team SENDS (true on /trade:
 * `computeSideFlowAssets` routes every 2-team asset to the other side).
 * Then the bigger package is the side giving up more, so "Side A wins"
 * would name the team that overpays; the copy names the package and the
 * team that receives it instead.  /waivers (Drop vs Add, not an exchange)
 * leaves it off and keeps its original wording.
 */
export function TradeMeterTwoTeam({ sides, sideTotals, sidesSend = false }) {
  const evalState = tradeEvaluationState(sides);
  if (evalState.state === TRADE_EVAL_STATE.EMPTY) {
    return <TradeMeterEmpty />;
  }
  const incomplete = evalState.state === TRADE_EVAL_STATE.INCOMPLETE;
  const pwA = sideTotals[0]?.adjusted || 0;
  const pwB = sideTotals[1]?.adjusted || 0;
  const gap = pwA - pwB;
  const absGap = Math.abs(gap);
  const pctGap = percentageGap(pwA, pwB);
  // ONE fairness-band owner (TC-C): relative to the larger adjusted side,
  // with an absolute minimum.  The badge and the winner text read the SAME
  // band, so "FAIR" can no longer sit beside "worth 7% more".
  const verdict = meterVerdict(gap, Math.max(pwA, pwB));
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
  if (verdict.level !== "fair") {
    const [big, small] = gap > 0 ? [labelA, labelB] : [labelB, labelA];
    winnerText = sidesSend
      ? `${big}'s package is worth ${pctGap}% more — ${small} receives more value`
      : `${big} wins by ${pctGap}%`;
  }

  return (
    <div className="trade-meter" role="group" aria-label="Package comparison">
      {/* Value comparison */}
      <div className="trade-meter-values">
        <span className="trade-meter-side-val">{Math.round(pwA).toLocaleString()}</span>
        <span className="trade-meter-vs">vs</span>
        <span className="trade-meter-side-val">{Math.round(pwB).toLocaleString()}</span>
        <span className="trade-meter-gap">
          {incomplete ? "Gap: not computed" : `Gap: ${Math.round(absGap).toLocaleString()}`}
        </span>
      </div>

      {incomplete ? (
        <TradeMeterIncomplete unpriced={evalState.unpriced} sides={sides} />
      ) : (
        <>
          {/* Horizontal balance bar.  Screen readers get its reading as one
              image name (TC-E); the fills themselves carry no text. */}
          <div
            className="trade-meter-bar"
            role="img"
            aria-label={`${labelA} ${Math.round(shareA)}% and ${labelB} ${Math.round(shareB)}% of the combined adjusted value`}
          >
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
          <div className="trade-meter-bar-labels" aria-hidden="true">
            <span className="muted" style={{ fontSize: "0.66rem" }}>
              {sides[0]?.label ? `Side ${sides[0].label}` : "Side A"}
            </span>
            <span className="muted" style={{ fontSize: "0.66rem" }}>
              {sides[1]?.label ? `Side ${sides[1].label}` : "Side B"}
            </span>
          </div>

          {/* Verdict badge + percentage */}
          <div className="trade-meter-bottom">
            <span className="ds-visually-hidden">Quick verdict: </span>
            <span className={`trade-meter-verdict trade-meter-verdict-${verdict.level}`}>
              {verdict.label}
            </span>
            <span className="trade-meter-pct">{winnerText}</span>
          </div>
        </>
      )}

      {/* Monte Carlo simulator — renders nothing when flag off, a
          button when flag on and trade has assets, or a "flag off"
          pill when backend returns 503.  Wrapped in ResilientSection
          so an MC-panel crash doesn't take down the trade meter. */}
      <ResilientSection name="Monte Carlo panel">
        <MonteCarloButton sides={sides} sidesSend={sidesSend} />
      </ResilientSection>
    </div>
  );
}

// The War Room's final market-fairness words (FAIR / NOT_FAIR / UNABLE), shown
// in place of the preliminary tags once it has answered this trade.
const FINAL_FAIRNESS_WORDS = {
  FAIR: "Fair",
  NOT_FAIR: "Not fair",
  UNABLE: "Unable to determine",
};

export function TradeMeterMultiTeam({ sides, sideTotals, flows, finalBySide = null }) {
  const evalState = tradeEvaluationState(sides);
  if (evalState.state === TRADE_EVAL_STATE.EMPTY) return <TradeMeterEmpty />;
  if (evalState.state === TRADE_EVAL_STATE.INCOMPLETE) {
    return (
      <div className="trade-meter">
        <TradeMeterIncomplete unpriced={evalState.unpriced} sides={sides} />
      </div>
    );
  }
  // In 3+-team trades each team is read in its OWN perspective (spec
  // docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1): ``net`` is that team's
  // adjusted gap (what it receives minus what it sends, each package valued
  // with the active Value Adjustment) and its band is relative to its OWN
  // larger package.  One helper, shared with the page's persistent 3+-team
  // summary (TC-D2).  PRELIMINARY: the final per-team result is the War
  // Room's (POST /api/trade/analyze-multi).
  const flowList =
    Array.isArray(flows) && flows.length === sides.length
      ? flows
      : sides.map(() => ({ given: 0, received: 0, net: 0 }));
  // A team whose part of the trade carries a WITHHELD value (quarantined /
  // stale — the same stamps the engine's evidence gates read) shows no gap
  // and no band: WITHHELD with the reason, never the sum that withheld
  // number sits in and never 0.  The headline is then not determinable.
  const withheldBySide = withheldAssetsBySide(sides);
  const { nets, perTeam, worst, worstIndex, verdict, withheld } = multiTeamNetSummary(
    flowList,
    withheldBySide,
  );
  const withheldSides = sides
    .map((s, i) => (withheld[i] ? `Side ${s.label}` : null))
    .filter(Boolean);
  const isEvenNet = (i) => perTeam[i]?.level === "fair";
  // Display scale only (the bar's full width), never a verdict.
  const absMax = Math.max(1, ...nets.map((n) => Math.abs(n || 0)));

  const fmtSigned = (n) => {
    const sign = n > 0 ? "+" : n < 0 ? "−" : "";
    return `${sign}${Math.round(Math.abs(n)).toLocaleString()}`;
  };
  const netColor = (n, i) => {
    if (n == null) return "var(--muted)";
    if (isEvenNet(i)) return "var(--muted)";
    return n > 0 ? "var(--green)" : "var(--red)";
  };
  const netTag = (n, i) => {
    if (withheld[i]) return "Withheld";
    if (n == null) return "Unknown";
    if (isEvenNet(i)) return "Even";
    if (n > 0) return "Getting value";
    return "Losing value";
  };

  return (
    <div className="trade-meter" role="group" aria-label="Preliminary value per team">
      <p
        className="muted"
        style={{ fontSize: "0.68rem", margin: "0 0 6px" }}
        data-testid="trade-meter-preliminary"
      >
        {finalBySide
          ? "Preliminary package gaps from the calculator's values. Each team's final result, from the Trade War Room, is shown under its gap."
          : "Preliminary — each team's own package gap. The final result comes from Analyze in the Trade War Room."}
      </p>
      {/* Per-team gap row */}
      <div className="trade-meter-multi-values">
        {sides.map((s, i) => {
          const flow = flowList[i] || { given: 0, received: 0, net: 0 };
          return (
            <div
              key={s.id}
              className="trade-meter-multi-val"
              data-team-state={withheld[i] ? "withheld" : nets[i] == null ? "unknown" : "priced"}
            >
              <span className="label">Side {s.label}</span>
              <span className="trade-meter-side-val" style={{ color: netColor(nets[i], i) }}>
                {withheld[i] ? "Withheld" : nets[i] == null ? "—" : fmtSigned(nets[i])}
              </span>
              {finalBySide?.[i] ? (
                <span style={{ fontSize: "0.64rem" }} data-testid="trade-meter-final">
                  Final: {FINAL_FAIRNESS_WORDS[finalBySide[i].fairness] || "Unable to determine"}
                  {finalBySide[i].decision ? ` · ${finalBySide[i].decision}` : ""}
                </span>
              ) : (
                <span className="muted" style={{ fontSize: "0.64rem" }}>
                  {netTag(nets[i], i)}
                </span>
              )}
              {withheld[i] ? (
                <span
                  className="muted"
                  style={{ fontSize: "0.6rem" }}
                  data-testid="trade-meter-withheld"
                >
                  Not determinable — value withheld: {withheldReasonText(withheldBySide[i])}
                </span>
              ) : (
                <span className="muted" style={{ fontSize: "0.6rem" }}>
                  Give {Math.round(flow.given).toLocaleString()} · Get {Math.round(flow.received).toLocaleString()}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Zero-centered NET bar per side.  Each side gets 1/N of the
           horizontal axis; within its slot the fill grows left-from-
           center (red) or right-from-center (green) proportional to
           |net| / absMax. */}
      {/* Decorative: the per-side nets above and below carry the numbers. */}
      <div style={{ display: "flex", gap: 4, margin: "8px 0 4px" }} aria-hidden="true">
        {sides.map((s, i) => {
          const net = nets[i] || 0;
          const pct = absMax > 0 ? Math.min(100, (Math.abs(net) / absMax) * 100) : 0;
          const isPos = net > 0;
          const isEven = isEvenNet(i);
          const fillColor = isEven ? "var(--muted)" : isPos ? "var(--green)" : "var(--red)";
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
              title={`Side ${s.label}: ${
                withheld[i] ? "withheld" : nets[i] == null ? "unknown" : fmtSigned(net)
              }`}
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
              color: netColor(nets[i], i),
            }}
          >
            {s.label}: {withheld[i] ? "withheld" : nets[i] == null ? "—" : fmtSigned(nets[i])}
          </span>
        ))}
      </div>

      {/* Overall verdict — the preliminary reading only until the War Room's
          final answer for this trade exists; then it defers to it. */}
      {finalBySide ? (
        <div className="trade-meter-bottom">
          <span className="trade-meter-pct">
            Final per-team results are in the Trade War Room below.
          </span>
        </div>
      ) : (
        <div className="trade-meter-bottom">
          <span className="ds-visually-hidden">Quick verdict: </span>
          <span className={`trade-meter-verdict trade-meter-verdict-${verdict.level}`}>
            {verdict.label}
          </span>
          <span className="trade-meter-pct" style={{ marginLeft: 8 }}>
            {withheldSides.length
              ? `No overall reading: ${withheldSides.join(", ")} withheld (a quarantined or stale value is not priced)`
              : worstIndex == null || worst == null
              ? "Widest gap: unknown"
              : `Widest gap: Side ${sides[worstIndex]?.label ?? worstIndex + 1} ${fmtSigned(
                  nets[worstIndex],
                )}`}
          </span>
        </div>
      )}
    </div>
  );
}

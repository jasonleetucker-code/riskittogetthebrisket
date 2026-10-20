/**
 * TC-A — the headline verdict speaks only when there is something to grade.
 *
 * UX audit P0-6: an empty trade rendered "FAIR / Even" on a full green/red bar
 * in the meter and "FAIR, Gap 0" in the sticky tray.  "Nothing to evaluate"
 * is not an evaluation.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));

const { default: TradeMeter, TradeMeterTwoTeam } = await import("@/components/trade/TradeMeter");
const { tradeEvaluationState, TRADE_EVAL_STATE } = await import("@/lib/trade-logic");

afterEach(cleanup);

const empty = (n = 2) =>
  Array.from({ length: n }, (_, i) => ({ id: i, label: "ABCDE"[i], assets: [] }));
const zeroTotals = (n = 2) => Array.from({ length: n }, () => ({ raw: 0, adjustment: 0, adjusted: 0, utility: 0 }));

describe("empty trade", () => {
  it("is classified empty", () => {
    expect(tradeEvaluationState(empty()).state).toBe(TRADE_EVAL_STATE.EMPTY);
  });

  it("the 2-team meter renders no band, no badge and no winner text", () => {
    render(<TradeMeter sides={empty()} sideTotals={zeroTotals()} sidesSend />);
    expect(screen.queryByText(/FAIR/i)).toBeNull();
    expect(screen.queryByText(/^Even$/)).toBeNull();
    expect(document.querySelector(".trade-meter-bar")).toBeNull();
    expect(screen.getByText(/Add assets to compare the packages/)).toBeTruthy();
  });

  it("the two-team meter used directly (/waivers) also refuses", () => {
    render(<TradeMeterTwoTeam sides={empty()} sideTotals={zeroTotals()} />);
    expect(document.querySelector(".trade-meter-verdict")).toBeNull();
  });

  it("the multi-team meter renders no verdict either", () => {
    render(<TradeMeter sides={empty(3)} sideTotals={zeroTotals(3)} flows={zeroTotals(3)} />);
    expect(document.querySelector(".trade-meter-verdict")).toBeNull();
  });

  it("the sticky tray shows the empty state instead of a band", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    const tray = src.slice(src.indexOf('className="trade-sticky-tray"'));
    expect(tray).toMatch(/tradeIsEmpty \? \(\s*<div className="verdict"/);
    expect(tray).toMatch(/Add assets to compare/);
  });
});

describe("incomplete trade (an unpriced asset) — no verdict over a 0", () => {
  const priced = (name, v) => ({ name, rankDerivedValue: v, values: { full: v } });
  const ghost = (name) => ({ name, rankDerivedValue: null, values: { full: 0 } });
  const sides = (a, b) => [
    { id: 0, label: "A", assets: a },
    { id: 1, label: "B", assets: b },
  ];

  it("is classified incomplete and names the unpriced asset by side", () => {
    const st = tradeEvaluationState(sides([priced("Star", 6000)], [ghost("Ghost Rookie")]));
    expect(st.state).toBe(TRADE_EVAL_STATE.INCOMPLETE);
    expect(st.unpriced).toEqual([{ side: 1, name: "Ghost Rookie" }]);
  });

  it("a user override prices the row and completes the trade", () => {
    const st = tradeEvaluationState(
      sides([priced("Star", 6000)], [{ ...ghost("Ghost Rookie"), customValue: 1200 }]),
    );
    expect(st.state).toBe(TRADE_EVAL_STATE.COMPLETE);
  });

  it("the meter shows INCOMPLETE and no band, gap or winner text", () => {
    render(
      <TradeMeter
        sides={sides([priced("Star", 6000)], [ghost("Ghost Rookie")])}
        sideTotals={[{ adjusted: 6000, utility: 6000 }, { adjusted: 0, utility: 0 }]}
        sidesSend
      />,
    );
    expect(screen.getByText("INCOMPLETE")).toBeTruthy();
    expect(screen.getByText(/Ghost Rookie \(Side B\)/)).toBeTruthy();
    expect(screen.queryByText(/LOPSIDED|FAIR|SLIGHT EDGE|UNFAIR/)).toBeNull();
    expect(screen.queryByText(/worth \d+% more/)).toBeNull();
    expect(screen.getByText("Gap: not computed")).toBeTruthy();
    expect(document.querySelector(".trade-meter-bar")).toBeNull();
  });

  it("the multi-team meter refuses too", () => {
    render(
      <TradeMeter
        sides={[...sides([priced("Star", 6000)], [ghost("Ghost")]), { id: 2, label: "C", assets: [priced("X", 100)] }]}
        sideTotals={zeroTotals(3)}
        flows={zeroTotals(3)}
      />,
    );
    expect(screen.getByText("INCOMPLETE")).toBeTruthy();
  });

  it("the page's tray, balancers and explanation are gated on it", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    // TC-E: the balancer search reads a deferred snapshot (`b`), same gate.
    expect(src).toMatch(/if \(b\.tradeIsIncomplete\) return \{ list: \[\], teamName: null \};/);
    expect(src).toMatch(/if \(b\.tradeIsIncomplete\) return null;/);
    expect(src).toMatch(/Incomplete — \{evalState\.unpriced\.length\} unpriced, no verdict/);
    expect(src).toMatch(/tradeIsIncomplete \? null : \(\s*<TradeFairnessExplanation/);
  });
});

describe("War Room names every unpriced asset", () => {
  it("collects not-on-board and on-board-unpriced names once each", async () => {
    const { notPricedNames } = await import("@/lib/trade-war-room");
    const analysis = {
      lenses: { market: { detail: { unpricedIn: ["Ghost"], unresolvedOut: ["Typo Name"] } } },
    };
    expect(notPricedNames(analysis, { unresolvedOut: ["Typo Name"] })).toEqual(["Typo Name", "Ghost"]);
  });
});

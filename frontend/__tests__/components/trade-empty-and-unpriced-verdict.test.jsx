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
const zeroTotals = (n = 2) => Array.from({ length: n }, () => ({ raw: 0, adjustment: 0, adjusted: 0 }));

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

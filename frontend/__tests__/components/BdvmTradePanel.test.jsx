/**
 * BdvmTradePanel — the fundamentals check on /trade.
 *
 * The properties that matter:
 * 1. Silent-vanish degrade (rankings gap-column precedent for add-on
 *    surfaces): 503 / non-ok status / network error → the panel
 *    renders NOTHING, never a generic error beside the trade grade.
 * 2. An ok payload renders every strategy currency the backend
 *    returned, plus the unresolved-assets note — assets the board
 *    declines to price are LISTED, never silently zeroed.
 * 3. No request at all until both sides carry assets (empty trade →
 *    nothing to evaluate → no fetch, no panel).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, act } from "@testing-library/react";

import BdvmTradePanel from "@/components/BdvmTradePanel";

const OK_BODY = {
  status: "ok",
  byStrategy: {
    balanced: { sideA: 5000, sideB: 4200, edge: 800, edgePct: 17.4 },
    contender: { sideA: 4600, sideB: 4900, edge: -300, edgePct: -6.3 },
  },
  unresolved: { sideA: [], sideB: ["2027 Round 5 (mystery)"] },
};

function sidesWith(namesA, namesB) {
  const mk = (names) => ({
    assets: names.map((name) => ({ name, raw: { playerId: null } })),
  });
  return [mk(namesA), mk(namesB)];
}

function mockFetch(status, body) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

async function settle() {
  // 600ms debounce, then the fetch promise chain.
  await act(async () => {
    vi.advanceTimersByTime(700);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("BdvmTradePanel", () => {
  it("renders per-strategy rows and the unresolved note on ok", async () => {
    global.fetch = mockFetch(200, OK_BODY);
    render(
      <BdvmTradePanel
        sides={sidesWith(["Alpha Back"], ["Bravo Wide"])}
        leagueKey="dynasty_main"
      />,
    );
    await settle();

    expect(screen.getByText("Fundamentals check (BDVM)")).toBeInTheDocument();
    // Only the strategies the backend returned render.
    expect(screen.getByText("Balanced")).toBeInTheDocument();
    expect(screen.getByText("Contender")).toBeInTheDocument();
    expect(screen.queryByText("Rebuilder")).toBeNull();
    // Unpriced assets are listed, never silently dropped.
    expect(
      screen.getByText(/Not priced by the fundamental board/),
    ).toBeInTheDocument();
    expect(screen.getByText(/2027 Round 5 \(mystery\)/)).toBeInTheDocument();
  });

  it("vanishes silently on a 503 (flag off / not ready)", async () => {
    global.fetch = mockFetch(503, { error: "bdvm_disabled" });
    const { container } = render(
      <BdvmTradePanel
        sides={sidesWith(["Alpha Back"], ["Bravo Wide"])}
        leagueKey="dynasty_main"
      />,
    );
    await settle();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(container).toBeEmptyDOMElement();
  });

  it("vanishes silently on a network error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("boom"));
    const { container } = render(
      <BdvmTradePanel
        sides={sidesWith(["Alpha Back"], ["Bravo Wide"])}
        leagueKey="dynasty_main"
      />,
    );
    await settle();
    expect(container).toBeEmptyDOMElement();
  });

  it("makes no request while either side is empty", async () => {
    global.fetch = mockFetch(200, OK_BODY);
    const { container } = render(
      <BdvmTradePanel sides={sidesWith(["Alpha Back"], [])} leagueKey="dynasty_main" />,
    );
    await settle();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("makes no request for 3+ team trades (CES eval is two-sided)", async () => {
    global.fetch = mockFetch(200, OK_BODY);
    const sides = [
      ...sidesWith(["Alpha Back"], ["Bravo Wide"]),
      { assets: [{ name: "Charlie End", raw: { playerId: null } }] },
    ];
    const { container } = render(
      <BdvmTradePanel sides={sides} leagueKey="dynasty_main" />,
    );
    await settle();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });
});

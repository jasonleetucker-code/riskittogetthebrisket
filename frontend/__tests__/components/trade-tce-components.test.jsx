/**
 * TC-E — reliability and accessibility of the /trade panels, one component at
 * a time.
 *
 *   - the verdict announcer: polite, debounced, the FINAL decision only, never
 *     a decision that was replaced before it settled, re-read after a clear;
 *   - out-of-order answers: Save to Trade Desk, the Monte Carlo error, the ROS
 *     fit league switch, partner evidence, recorded real trades and the BDVM
 *     check never let an older answer speak for a newer trade;
 *   - explicit loading / error-with-retry / partial / unavailable states: the
 *     War Room, ROS fit, partner evidence and recorded real trades never
 *     render a blank or a zero where an answer is missing;
 *   - screen-reader semantics of the meter.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));

import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";
import FORCED from "../fixtures/trade-war-room/forced-cut.json";

const {
  TradeVerdictAnnouncer,
  VERDICT_ANNOUNCE_DELAY_MS,
  verdictAnnouncement,
} = await import("@/app/trade/trade-layout");
const { default: TradeWarRoom } = await import("@/components/trade/TradeWarRoom");
const { default: SaveToDeskButton } = await import("@/components/trade/SaveToDeskButton");
const { default: MonteCarloButton } = await import("@/components/ui/MonteCarloButton");
const RosMod = await import("@/components/RosTradeFitPanel");
const RosTradeFitPanel = RosMod.default;
const { default: TradeNextActions } = await import("@/components/trade/TradeNextActions");
const { default: RecentRealTrades } = await import("@/components/trade/RecentRealTrades");
const { default: BdvmTradePanel } = await import("@/components/BdvmTradePanel");
const { TradeMeterTwoTeam } = await import("@/components/trade/TradeMeter");

const ok = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

/** fetch answers released by hand, in any order. */
function deferredFetch() {
  const pending = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(
    (url, init) =>
      new Promise((resolve) => {
        pending.push({ url: String(url), init, resolve: (body, status) => resolve(ok(body, status)) });
      }),
  );
  return { pending, spy };
}

// Some cases assign `globalThis.fetch = vi.fn()` (the War Room suite's
// pattern); put the original back so no mock history leaks between cases.
const ORIGINAL_FETCH = globalThis.fetch;
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  globalThis.fetch = ORIGINAL_FETCH;
});

// ── Verdict announcer ──────────────────────────────────────────────────
describe("TradeVerdictAnnouncer — only the final decision, politely, once (TC-E)", () => {
  const A = CONSOLIDATION.analysis.decision;
  const B = { ...A, headline: "NO_TOO_CLOSE", headlineText: "NO — TOO CLOSE" };
  const region = () => screen.getByTestId("trade-verdict-announcer");

  beforeEach(() => vi.useFakeTimers());

  it("is a polite, atomic status region that starts empty", () => {
    render(<TradeVerdictAnnouncer summary={{ status: "idle", decision: null }} />);
    expect(region().getAttribute("role")).toBe("status");
    expect(region().getAttribute("aria-live")).toBe("polite");
    expect(region().getAttribute("aria-atomic")).toBe("true");
    expect(region().textContent).toBe("");
  });

  it("announces a settled decision after the delay, with the backend's own confidence level", () => {
    render(<TradeVerdictAnnouncer summary={{ status: "ok", decision: A }} />);
    expect(region().textContent).toBe("");
    act(() => vi.advanceTimersByTime(VERDICT_ANNOUNCE_DELAY_MS));
    expect(region().textContent).toBe(
      `Final decision: ${A.headlineText}. Confidence: ${A.confidence.level.toLowerCase()}.`,
    );
  });

  it("never reads a decision that was replaced before it settled", () => {
    const view = render(<TradeVerdictAnnouncer summary={{ status: "ok", decision: A }} />);
    act(() => vi.advanceTimersByTime(VERDICT_ANNOUNCE_DELAY_MS / 2));
    view.rerender(<TradeVerdictAnnouncer summary={{ status: "updating", decision: A }} />);
    view.rerender(<TradeVerdictAnnouncer summary={{ status: "ok", decision: B }} />);
    act(() => vi.advanceTimersByTime(VERDICT_ANNOUNCE_DELAY_MS - 1));
    expect(region().textContent).toBe("");
    act(() => vi.advanceTimersByTime(1));
    expect(region().textContent).toMatch(/NO — TOO CLOSE/);
    expect(region().textContent).not.toMatch(/MAKE THE TRADE/);
  });

  it("says nothing for loading, errors or 3+-team trades", () => {
    const view = render(<TradeVerdictAnnouncer summary={{ status: "loading", decision: null }} />);
    for (const status of ["updating", "error", "multi", "no-team", "side-choice"]) {
      view.rerender(<TradeVerdictAnnouncer summary={{ status, decision: null }} />);
      act(() => vi.advanceTimersByTime(VERDICT_ANNOUNCE_DELAY_MS * 2));
      expect(region().textContent).toBe("");
    }
  });

  it("re-reads the same words after the trade was cleared and built again", () => {
    const view = render(<TradeVerdictAnnouncer summary={{ status: "ok", decision: A }} />);
    act(() => vi.advanceTimersByTime(VERDICT_ANNOUNCE_DELAY_MS));
    expect(region().textContent).toMatch(/MAKE THE TRADE/);
    view.rerender(<TradeVerdictAnnouncer summary={{ status: "idle", decision: null }} />);
    expect(region().textContent).toBe("");
    view.rerender(<TradeVerdictAnnouncer summary={{ status: "ok", decision: A }} />);
    act(() => vi.advanceTimersByTime(VERDICT_ANNOUNCE_DELAY_MS));
    expect(region().textContent).toMatch(/MAKE THE TRADE/);
  });

  it("verdictAnnouncement builds no text of its own beyond the label words", () => {
    expect(verdictAnnouncement({ status: "updating", decision: A })).toBeNull();
    expect(verdictAnnouncement({ status: "ok", decision: { ...A, confidence: null } })).toBe(
      `Final decision: ${A.headlineText}.`,
    );
  });

  it("the page mounts exactly one announcer, outside the responsive columns", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    expect(src.match(/<TradeVerdictAnnouncer\b/g)).toHaveLength(1);
    expect(src.indexOf("<TradeVerdictAnnouncer")).toBeLessThan(src.indexOf("<TradeSectionNav />"));
  });
});

// ── War Room: progress is not a live region; error has Try again ───────
describe("TradeWarRoom states (TC-E)", () => {
  const req = (fixture) => ({ ...fixture._fixture.request, mySide: 0 });
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  async function settle() {
    await act(async () => {
      vi.advanceTimersByTime(800);
    });
    await act(async () => {});
  }

  it("an analysis error offers Try again, which re-asks the same question", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok({ error: "boom" }, 500))
      .mockResolvedValueOnce(ok(CONSOLIDATION));
    render(<TradeWarRoom request={req(CONSOLIDATION)} leagueKey="main" useTeamContext />);
    await settle();
    expect(screen.getByText(/Analysis unavailable right now/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await settle();
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    const [, second] = globalThis.fetch.mock.calls;
    expect(JSON.parse(second[1].body)).toEqual(JSON.parse(globalThis.fetch.mock.calls[0][1].body));
    expect(screen.getByTestId("decision-headline")).toHaveTextContent(
      CONSOLIDATION.analysis.decision.headlineText,
    );
  });

  it("'Analyzing…' is visible but not announced; the answer carries a screen-reader name", async () => {
    globalThis.fetch = vi.fn(async () => ok(FORCED));
    render(<TradeWarRoom request={req(FORCED)} leagueKey="main" useTeamContext />);
    expect(screen.getByText("Analyzing this trade…")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    await settle();
    const line = screen.getByTestId("decision-headline").parentElement;
    expect(line.textContent.startsWith("Final decision: ")).toBe(true);
    // The badge itself stays the backend's words, verbatim.
    expect(screen.getByTestId("decision-headline").textContent).toBe(
      FORCED.analysis.decision.headlineText,
    );
  });
});

// ── Save to Trade Desk ─────────────────────────────────────────────────
describe("SaveToDeskButton — a save in flight belongs to its package", () => {
  const body = (name) => ({
    leagueKey: "dynasty_main",
    myTeam: "Jason",
    opponent: "Ed",
    source: "calculator",
    send: [{ name, isPick: false }],
    receive: [{ name: "Other", isPick: false }],
  });

  it("a save that answers after the card moved to another package says nothing about the new one", async () => {
    const { pending } = deferredFetch();
    const view = render(<SaveToDeskButton body={body("Old Package")} />);
    fireEvent.click(screen.getByRole("button", { name: "Save to Trade Desk" }));
    view.rerender(<SaveToDeskButton body={body("New Package")} />);
    await act(async () => pending[0].resolve({ items: [] }));
    expect(screen.queryByText("Saved to your Trade Desk")).toBeNull();
    expect(screen.getByRole("button", { name: "Save to Trade Desk" })).toBeTruthy();
  });

  it("the same package still reports its save", async () => {
    const { pending } = deferredFetch();
    render(<SaveToDeskButton body={body("Same")} />);
    fireEvent.click(screen.getByRole("button", { name: "Save to Trade Desk" }));
    await act(async () => pending[0].resolve({ items: [] }));
    expect(screen.getByText("Saved to your Trade Desk")).toBeTruthy();
  });
});

// ── Monte Carlo error ──────────────────────────────────────────────────
describe("MonteCarloButton — an error belongs to its trade", () => {
  const row = (name, v) => ({ name, rankDerivedValue: v, values: { full: v }, pos: "WR" });
  const ghost = (name) => ({ name, pos: "WR", values: {} });
  const sides = (a, b) => [
    { label: "A", assets: a },
    { label: "B", assets: b },
  ];

  it("'Can't simulate: X has no value' disappears once X is removed", async () => {
    const view = render(<MonteCarloButton sides={sides([row("P", 5000)], [ghost("Ghost")])} sidesSend />);
    fireEvent.click(screen.getByRole("button", { name: /Simulate/ }));
    expect(await screen.findByText(/Can't simulate: Ghost/)).toBeTruthy();
    view.rerender(<MonteCarloButton sides={sides([row("P", 5000)], [row("K", 4000)])} sidesSend />);
    expect(screen.queryByText(/Can't simulate/)).toBeNull();
  });

  it("an HTTP error from a slow run for the previous trade never shows under the new one", async () => {
    const { pending } = deferredFetch();
    const view = render(<MonteCarloButton sides={sides([row("P", 5000)], [row("K", 4000)])} sidesSend />);
    fireEvent.click(screen.getByRole("button", { name: /Simulate/ }));
    view.rerender(
      <MonteCarloButton sides={sides([row("P", 5000)], [row("K", 4000), row("B", 3000)])} sidesSend />,
    );
    await act(async () => pending[0].resolve({}, 500));
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
  });
});

// ── ROS fit ────────────────────────────────────────────────────────────
describe("RosTradeFitPanel — explicit states, never a blank tab (TC-E)", () => {
  const SIDES = [
    { label: "A", assets: [{ name: "P1", pos: "WR" }] },
    { label: "B", assets: [{ name: "P2", pos: "RB" }] },
  ];
  let league = 0;
  const nextLeague = () => `tce_league_${(league += 1)}`;

  it("says it is loading, then says the data is unavailable, and Try again recovers", async () => {
    const { pending } = deferredFetch();
    render(<RosTradeFitPanel sides={SIDES} settings={{}} leagueKey={nextLeague()} />);
    expect(screen.getByTestId("ros-fit-loading")).toBeTruthy();
    await act(async () => {
      for (const p of pending.splice(0)) p.resolve({}, 503);
    });
    expect(await screen.findByTestId("ros-fit-error")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByTestId("ros-fit-loading")).toBeTruthy();
    await act(async () => {
      for (const p of pending.splice(0)) {
        p.resolve(p.url.includes("rosTradeDeadline") ? { teams: [{ teamName: "X", label: "Buyer" }] } : { players: [] });
      }
    });
    expect(await screen.findByTestId("ros-fit-public-deadline-note")).toBeTruthy();
  });

  it("one read failing is a labelled partial answer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      String(url).includes("rosTradeDeadline") ? ok({ teams: [{ teamName: "X" }] }) : ok({}, 500),
    );
    render(<RosTradeFitPanel sides={SIDES} settings={{}} leagueKey={nextLeague()} />);
    expect((await screen.findByTestId("ros-fit-partial")).textContent).toMatch(
      /Player rest-of-season values are unavailable/,
    );
  });

  it("nothing to read is said in words; switched off is said in words", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      String(url).includes("rosTradeDeadline") ? ok({ teams: [] }) : ok({ players: [] }),
    );
    const view = render(<RosTradeFitPanel sides={SIDES} settings={{}} leagueKey={nextLeague()} />);
    expect((await screen.findByTestId("ros-fit-empty")).textContent).toMatch(/No rest-of-season read/);
    view.rerender(<RosTradeFitPanel sides={SIDES} settings={{ showRosTradePanel: false }} leagueKey="x" />);
    expect(screen.getByTestId("ros-fit-off").textContent).toMatch(/turned off in Settings/);
  });

  it("a slow answer for the previous league never lands on the new one", async () => {
    const { pending } = deferredFetch();
    const first = nextLeague();
    const second = nextLeague();
    const view = render(<RosTradeFitPanel sides={SIDES} settings={{}} leagueKey={first} />);
    view.rerender(<RosTradeFitPanel sides={SIDES} settings={{}} leagueKey={second} />);
    const forLeague = (k) => pending.find((p) => p.url.includes(`leagueKey=${k}`));
    await act(async () => {
      forLeague(second).resolve({ teams: [] });
      for (const p of pending.filter((p) => p.url.includes("player-values"))) p.resolve({ players: [] });
    });
    await screen.findByTestId("ros-fit-empty");
    await act(async () => forLeague(first).resolve({ teams: [{ teamName: "Old league team" }] }));
    expect(screen.getByTestId("ros-fit-empty")).toBeTruthy();
  });
});

// ── Partner evidence ───────────────────────────────────────────────────
describe("partner evidence — error offers Try again (TC-E)", () => {
  const P = (name, pos, playerId) => ({ name, pos, assetClass: "offense", playerId });
  const BASE = {
    sides: [
      { label: "A", assets: [P("Give WR", "WR", "11")] },
      { label: "B", assets: [P("Get RB", "RB", "22")] },
    ],
    leagueKey: "dynasty_main",
    myTeam: "Jason",
    mySideIdx: 0,
    sideTeamNames: ["Jason", "Joey"],
    evalState: "complete",
    isFair: false,
    balancerSideLabel: "A",
  };

  it("re-asks after an error", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ok({ error: "scout_down" }, 503))
      .mockResolvedValueOnce(ok({ error: "still_down" }, 503));
    render(<TradeNextActions {...BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /trade history for this package/ }));
    expect(await screen.findByText(/Manager history unavailable right now \(scout_down\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/still_down/)).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});

// ── Recorded real trades ───────────────────────────────────────────────
describe("RecentRealTrades — sequencing and retry (TC-E)", () => {
  const P = (name, playerId) => ({ name, pos: "WR", assetClass: "offense", playerId, raw: { playerId } });
  const sidesWith = (...names) => [
    { label: "A", assets: names.map((n, i) => P(n, `p${i}`)) },
    { label: "B", assets: [] },
  ];
  const body = (n) => ({ state: "ok", since: "2026-01-01", trades: [], scanCapped: false, ledger: {}, tag: n });

  it("an unreadable ledger offers Try again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ok({ state: "unavailable" }))
      .mockResolvedValueOnce(ok(body(1)));
    render(<RecentRealTrades sides={sidesWith("A1")} leagueKey="dynasty_main" />);
    await act(async () => vi.advanceTimersByTime(450));
    expect(await screen.findByText("Real-trade evidence unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await act(async () => vi.advanceTimersByTime(450));
    expect(await screen.findByText(/No recorded trades/)).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("a lookup for the previous package that answers last never replaces the current one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { pending } = deferredFetch();
    const view = render(<RecentRealTrades sides={sidesWith("A1")} leagueKey="dynasty_main" />);
    await act(async () => vi.advanceTimersByTime(450));
    view.rerender(<RecentRealTrades sides={sidesWith("A1", "A2")} leagueKey="dynasty_main" />);
    await act(async () => vi.advanceTimersByTime(450));
    expect(pending.length).toBe(2);
    await act(async () => pending[1].resolve(body(2)));
    expect(await screen.findByText(/No recorded trades/)).toBeTruthy();
    await act(async () => pending[0].resolve({ state: "unavailable" }));
    expect(screen.queryByText("Real-trade evidence unavailable")).toBeNull();
    expect(screen.getByText(/No recorded trades/)).toBeTruthy();
  });
});

// ── BDVM check ─────────────────────────────────────────────────────────
describe("BdvmTradePanel — an answer renders only for its own trade", () => {
  it("hides the previous trade's answer as soon as the trade changes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { pending } = deferredFetch();
    const row = (name) => ({ name, pos: "WR", raw: { playerId: name } });
    const sides = (b) => [
      { label: "A", assets: [row("A1")] },
      { label: "B", assets: b.map(row) },
    ];
    const answer = {
      status: "ok",
      byStrategy: {},
      unresolved: { sideA: [], sideB: [] },
    };
    const view = render(<BdvmTradePanel sides={sides(["B1"])} leagueKey="dynasty_main" />);
    await act(async () => vi.advanceTimersByTime(650));
    await act(async () => pending[0].resolve(answer));
    const shown = document.body.innerHTML.length;
    expect(shown).toBeGreaterThan(0);
    view.rerender(<BdvmTradePanel sides={sides(["B1", "B2"])} leagueKey="dynasty_main" />);
    expect(view.container.innerHTML).toBe("");
  });
});

// ── Meter semantics ────────────────────────────────────────────────────
describe("TradeMeter — screen-reader semantics (TC-E)", () => {
  it("a named group, the bar as one image name, and a labelled quick verdict", () => {
    const priced = (name, v) => ({ name, pos: "WR", values: { full: v }, rankDerivedValue: v });
    render(
      <TradeMeterTwoTeam
        sides={[
          { label: "A", assets: [priced("X", 6000)] },
          { label: "B", assets: [priced("Y", 4000)] },
        ]}
        sideTotals={[
          { raw: 6000, adjustment: 0, adjusted: 6000 },
          { raw: 4000, adjustment: 0, adjusted: 4000 },
        ]}
        sidesSend
      />,
    );
    const group = screen.getByRole("group", { name: "Package comparison" });
    expect(within(group).getByRole("img").getAttribute("aria-label")).toBe(
      "Side A 60% and Side B 40% of the combined adjusted value",
    );
    expect(group.textContent).toMatch(/Quick verdict: /);
  });
});

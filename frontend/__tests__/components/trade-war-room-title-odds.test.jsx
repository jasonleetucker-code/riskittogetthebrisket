/**
 * TradeWarRoom — "This season's odds" (DYN10 #4, `POST /api/trade/title-odds`).
 *
 * The panel exists only when the server's `tradeTitleOdds` capability is true
 * (owner-held flag `trade_title_odds_lens`, default OFF): with it false the
 * War Room makes NO request to the route.  With it true the panel asks AFTER
 * the analysis has arrived (the recommendation never waits), shows a loading
 * state, then every team's playoff and title odds before → after with the
 * change and its interval, "Within simulation noise" when the change is not
 * significant, every unavailable reason in words (never 0), and the owner-
 * approved uncalibrated-odds disclosure in every state.
 *
 * The analysis is a REAL `POST /api/trade/analyze` fixture; the season-odds
 * payloads follow `src/trade/title_odds_lens.py`'s shape.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TradeWarRoom from "@/components/trade/TradeWarRoom";
import { ODDS_EXPERIMENTAL_DISCLOSURE } from "@/lib/odds-disclosure";
import {
  formatPointChange,
  oddsCell,
  titleOddsReasonText,
  titleOddsRows,
} from "@/lib/trade-title-odds";

import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";

const ROUTE = "/api/trade/title-odds";
const req = (fixture) => ({ ...(fixture._fixture?.request || {}), mySide: 0 });

function ok(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

/** One odds row in the lens's shape. */
function odds(before, after, delta, deltaCi, significant) {
  return { before, after, delta, deltaCi, significant };
}

const ODDS_OK = {
  version: "trade_title_odds_v1",
  state: "ok",
  role: "context_not_vote",
  leagueKey: "main",
  perspectiveOwnerId: "o1",
  counterpartyInferred: true,
  disclosure: { text: ODDS_EXPERIMENTAL_DISCLOSURE },
  teams: [
    {
      ownerId: "o2",
      displayName: "Them",
      available: true,
      playoff: odds(0.6, 0.52, -0.08, [-0.12, -0.04], true),
      championship: odds(0.12, 0.11, -0.01, [-0.03, 0.01], false),
    },
    {
      ownerId: "o1",
      displayName: "Us",
      available: true,
      playoff: odds(0.4, 0.47, 0.07, [0.03, 0.11], true),
      championship: odds(0.08, 0.09, 0.01, [-0.01, 0.03], false),
    },
  ],
};

function unavailable(reason) {
  return {
    version: "trade_title_odds_v1",
    state: "unavailable",
    reason,
    teams: [],
    disclosure: { text: ODDS_EXPERIMENTAL_DISCLOSURE },
  };
}

/** Routes the War Room's two requests; `titleOdds` gets the init. */
function stubFetch(titleOdds) {
  const fn = vi.fn(async (url, init) => {
    if (String(url).includes(ROUTE)) return titleOdds(init);
    return ok(CONSOLIDATION);
  });
  globalThis.fetch = fn;
  return fn;
}

const titleOddsCalls = (fn) => fn.mock.calls.filter(([url]) => String(url).includes(ROUTE));

async function settle(ms = 800) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await act(async () => {});
  await act(async () => {});
}

async function renderRoom(props = {}) {
  const view = render(
    <TradeWarRoom request={req(CONSOLIDATION)} leagueKey="main" useTeamContext {...props} />,
  );
  await settle();
  return view;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("capability off", () => {
  it("renders no panel and never calls the route", async () => {
    const fn = stubFetch(async () => ok(ODDS_OK));
    await renderRoom();
    expect(screen.getByTestId("decision-headline")).toBeTruthy();
    expect(titleOddsCalls(fn)).toHaveLength(0);
    expect(screen.queryByTestId("war-room-title-odds")).toBeNull();
  });

  it("still makes no request in Asset only, even with the capability on", async () => {
    const fn = stubFetch(async () => ok(ODDS_OK));
    await renderRoom({ titleOddsAvailable: true, useTeamContext: false });
    expect(titleOddsCalls(fn)).toHaveLength(0);
    expect(screen.queryByTestId("war-room-title-odds")).toBeNull();
  });
});

describe("capability on", () => {
  it("asks after the analysis, with the analysis body minus the strategy, and shows loading", async () => {
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    const fn = stubFetch(() => pending);
    await renderRoom({ titleOddsAvailable: true });
    const calls = titleOddsCalls(fn);
    expect(calls).toHaveLength(1);
    // The analysis was asked first.
    expect(String(fn.mock.calls[0][0])).toContain("/api/trade/analyze");
    const body = JSON.parse(calls[0][1].body);
    expect(body).toEqual({
      teamName: "Us",
      playersIn: ["WR Buf Star"],
      playersOut: ["WR Kc", "WR Phi"],
      picksIn: [],
      picksOut: [],
      pickAssetIdsIn: [],
      pickAssetIdsOut: [],
      useTeamContext: true,
      leagueKey: "main",
    });
    expect(screen.getByTestId("title-odds-loading")).toBeTruthy();
    expect(screen.getByTestId("title-odds-disclosure")).toHaveTextContent(
      ODDS_EXPERIMENTAL_DISCLOSURE,
    );
    await act(async () => {
      release(ok(ODDS_OK));
    });
    await settle(0);
    expect(screen.queryByTestId("title-odds-loading")).toBeNull();
  });

  it("shows each team's odds before → after with the change, its range and a noise flag", async () => {
    stubFetch(async () => ok(ODDS_OK));
    await renderRoom({ titleOddsAvailable: true });
    const panel = screen.getByTestId("war-room-title-odds");
    expect(within(panel).getByRole("heading", { name: "This season's odds" })).toBeTruthy();
    const rows = panel.querySelectorAll("tbody tr");
    // The analysed team leads.
    expect(rows[0].getAttribute("data-team")).toBe("o1");
    expect(rows[0]).toHaveTextContent("Your team");
    expect(rows[0]).toHaveTextContent("40% → 47% +7.0 points (range +3.0 to +11.0)");
    expect(rows[0]).toHaveTextContent("8% → 9% +1.0 points (range −1.0 to +3.0)");
    expect(rows[1]).toHaveTextContent("60% → 52% −8.0 points (range −12.0 to −4.0)");
    // Only the non-significant title changes carry the noise flag.
    expect(within(rows[0]).getAllByTestId("title-odds-noise")).toHaveLength(1);
    expect(within(rows[1]).getAllByTestId("title-odds-noise")).toHaveLength(1);
    expect(panel).toHaveTextContent("Within simulation noise.");
    expect(panel).toHaveTextContent("Context only: this does not change the recommendation.");
    expect(panel).toHaveTextContent("current holder of the players you receive");
    expect(screen.getByTestId("title-odds-disclosure")).toHaveTextContent(
      ODDS_EXPERIMENTAL_DISCLOSURE,
    );
    // The recommendation is still the analysis's own.
    expect(screen.getByTestId("decision-headline")).toHaveTextContent(
      CONSOLIDATION.analysis.decision.headlineText,
    );
  });

  it("says an unavailable answer in words, never as 0, with the disclosure", async () => {
    stubFetch(async () => ok(unavailable("no_remaining_schedule")));
    await renderRoom({ titleOddsAvailable: true });
    const panel = screen.getByTestId("war-room-title-odds");
    expect(screen.getByTestId("title-odds-unavailable")).toHaveTextContent(
      "Season odds are unavailable: no regular-season games are left on the schedule",
    );
    expect(panel.querySelector("table")).toBeNull();
    expect(panel.textContent).not.toMatch(/\b0%/);
    expect(screen.getByTestId("title-odds-disclosure")).toHaveTextContent(
      ODDS_EXPERIMENTAL_DISCLOSURE,
    );
    // A refusal Retry cannot fix offers no Retry.
    expect(within(panel).queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("offers Retry after a timeout and asks again", async () => {
    const answers = [ok(unavailable("title_odds_timeout")), ok(ODDS_OK)];
    const fn = stubFetch(async () => answers.shift());
    await renderRoom({ titleOddsAvailable: true });
    expect(screen.getByTestId("title-odds-unavailable")).toHaveTextContent("took too long");
    const panel = screen.getByTestId("war-room-title-odds");
    fireEvent.click(within(panel).getByRole("button", { name: "Retry" }));
    await settle(0);
    expect(titleOddsCalls(fn)).toHaveLength(2);
    expect(screen.getByTestId("war-room-title-odds").querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("names a refused request in words", async () => {
    stubFetch(async () => ok({ error: "feature_disabled" }, 503));
    await renderRoom({ titleOddsAvailable: true });
    expect(screen.getByTestId("title-odds-error")).toHaveTextContent(
      "Season odds are unavailable: season odds are switched off.",
    );
  });

  it("names a team the simulation could not place, and a title odd it could not publish", async () => {
    const payload = structuredClone(ODDS_OK);
    payload.teams[0] = {
      ownerId: "o2",
      displayName: "Them",
      available: false,
      unavailableReason: "team_not_in_simulation",
    };
    payload.teams[1].championship = null;
    payload.teams[1].championshipUnavailable = { reason: "playoff_seed_type_unknown" };
    stubFetch(async () => ok(payload));
    await renderRoom({ titleOddsAvailable: true });
    const rows = screen.getByTestId("war-room-title-odds").querySelectorAll("tbody tr");
    expect(rows[0]).toHaveTextContent(
      "Not published: this league's settings do not say how its playoff bracket is seeded",
    );
    expect(rows[1]).toHaveTextContent("Not simulated: this team is not in the season simulation.");
  });
});

describe("wording helpers", () => {
  it("formats changes in percentage points and keeps missing missing", () => {
    expect(formatPointChange(0.07)).toBe("+7.0");
    expect(formatPointChange(-0.0849)).toBe("−8.5");
    expect(formatPointChange(0)).toBe("0.0");
    expect(formatPointChange(null)).toBeNull();
    expect(oddsCell(null)).toBeNull();
    expect(oddsCell({ before: null, after: 0.5, delta: null })).toEqual({
      levels: "— → 50%",
      change: null,
      range: null,
      noise: false,
    });
    // A simulated share is never printed as 0% or 100%.
    expect(oddsCell({ before: 0, after: 1, delta: 1, significant: true }).levels).toBe("<1% → >99%");
  });

  it("never shows a reason code", () => {
    expect(titleOddsReasonText("some_new_engine_reason")).toBe(
      "the season simulation could not answer for this trade",
    );
    expect(titleOddsRows({ teams: [] }, "o1")).toEqual([]);
  });
});

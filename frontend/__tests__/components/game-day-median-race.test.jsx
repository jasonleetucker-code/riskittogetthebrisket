/**
 * Live Median Race (owner directive 2026-09-26) — through the real GameDayPanel.
 *
 * Payloads are REAL `/api/matchup/intel` output (the U4 replay through the
 * production endpoint; `tests/game_day/test_game_day_ui_fixtures.py` pins
 * them byte-equal), so every probability, margin, median and rank asserted
 * here is the backend's — the board computes none of them.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GameDayPanel from "@/components/GameDayPanel";
import { formatPct, formatPoints } from "@/lib/game-day-view";

import PREGAME from "../fixtures/game-day/pregame.json";
import HALFTIME from "../fixtures/game-day/halftime.json";
import OPPONENT from "../fixtures/game-day/halftime-opponent.json";
import WEEK_FINAL from "../fixtures/game-day/week-final.json";
import PENDING from "../fixtures/game-day/pending.json";

const mockUserState = { state: { selectedTeam: { ownerId: "owner-8" } } };
vi.mock("@/components/useUserState", () => ({ useUserState: () => mockUserState }));
const mockSearchParams = { value: new Map() };
const mockRouter = { push: vi.fn() };
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams.value,
  useRouter: () => mockRouter,
  usePathname: () => "/game-day",
}));
const mockLeague = { selectedLeagueKey: "dynasty_main", loading: false };
vi.mock("@/components/useLeague", () => ({ useLeague: () => mockLeague }));

const clone = (x) => JSON.parse(JSON.stringify(x));
const ok = (body) => ({ ok: true, status: 200, json: async () => body });
function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

function board() {
  return screen.getByRole("list", { name: /Teams (ranked by chance to beat the median|by final score)/ });
}
function rows() {
  return within(board()).getAllByRole("listitem");
}
function rowFor(rosterId) {
  return document.querySelector(`[data-roster-id="${rosterId}"]`);
}
async function show(payload) {
  globalThis.fetch = vi.fn(async () => ok(payload));
  const view = render(<GameDayPanel />);
  await screen.findByText(`Week ${payload.week} · ${payload.season}`);
  return view;
}

beforeEach(() => {
  mockUserState.state = { selectedTeam: { ownerId: "owner-8" } };
  mockSearchParams.value = new Map();
  mockRouter.push = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("Live Median Race — the board is the backend's", () => {
  it("sits directly after the hero and lists every roster once, in backend rank order", async () => {
    const { container } = await show(HALFTIME);
    const headings = [...container.querySelectorAll("h2")].map((h) => h.textContent.trim());
    expect(headings[0]).toBe("Live median race");
    const ids = rows().map((li) => li.getAttribute("data-roster-id"));
    expect(ids).toEqual(HALFTIME.medianRace.teams.map((t) => t.rosterId));
    expect(new Set(ids).size).toBe(HALFTIME.leagueTeams.length);
  });

  it("shows the projected median, its 80% range and the current median", async () => {
    await show(HALFTIME);
    const r = HALFTIME.medianRace;
    const summary = screen.getByRole("heading", { name: "Live median race" }).closest("section");
    expect(within(summary).getByText(formatPoints(r.projectedMedianMean))).toBeInTheDocument();
    expect(
      within(summary).getByText(`${formatPoints(r.projectedMedianP10)}–${formatPoints(r.projectedMedianP90)}`),
    ).toBeInTheDocument();
    expect(within(summary).getByText(formatPoints(r.currentMedian))).toBeInTheDocument();
  });

  it("names the bubble from the backend's probability-distance order", async () => {
    await show(HALFTIME);
    const bubble = screen.getByText("On the bubble").closest("div");
    const r = HALFTIME.medianRace;
    const first = r.teams.find((t) => t.rosterId === r.bubble[0]);
    expect(bubble.textContent).toContain(`${first.teamName} ${formatPct(first.beatMedianPct)}`);
  });

  it("marks the selected team with text, and its number equals the hero's", async () => {
    await show(HALFTIME);
    const sel = rowFor(HALFTIME.team.rosterId);
    const button = within(sel).getByRole("button");
    expect(button).toHaveAttribute("aria-current", "true");
    expect(within(sel).getByText("Viewing")).toBeInTheDocument();
    const heroPct = formatPct(HALFTIME.team.outcome.beatMedianPct);
    expect(within(sel).getByText(heroPct)).toBeInTheDocument();
    const heroRow = within(screen.getByRole("table", { name: /matchup:/ })).getByRole("row", { name: /Team 8/ });
    expect(within(heroRow).getByText(heroPct)).toBeInTheDocument();
  });

  it("gives each row an accessible name with rank and chance", async () => {
    await show(HALFTIME);
    const t = HALFTIME.medianRace.teams[0];
    expect(
      screen.getByRole("button", {
        name: new RegExp(`^Rank 1, ${t.teamName}, ${formatPct(t.beatMedianPct).replace(".", "\\.")} to beat the median`),
      }),
    ).toBeInTheDocument();
  });

  it("shows movement only where a comparable generation exists", async () => {
    await show(HALFTIME);
    const moved = HALFTIME.medianRace.teams.find((t) => typeof t.movementPp === "number" && t.movementPp > 0);
    // The arrow is visual; its meaning is in the row's accessible name.
    const button = within(rowFor(moved.rosterId)).getByRole("button");
    expect(button.getAttribute("aria-label")).toMatch(
      new RegExp(`up ${moved.movementPp.toFixed(1)}pp since the last update`),
    );
    expect(rowFor(moved.rosterId).querySelector(".ds-movement--up")).not.toBeNull();
  });

  it("has no movement arrows on the week's first generation", async () => {
    await show(PREGAME);
    expect(board().querySelectorAll(".ds-movement")).toHaveLength(0);
    for (const b of within(board()).getAllByRole("button")) {
      expect(b.getAttribute("aria-label")).not.toMatch(/since the last update/);
    }
  });
});

describe("Live Median Race — states", () => {
  it("final: actual results, the final median, no stale forecast", async () => {
    await show(WEEK_FINAL);
    expect(screen.getByRole("heading", { name: "Median race — final" })).toBeInTheDocument();
    expect(screen.getByText(formatPoints(WEEK_FINAL.medianRace.finalMedian))).toBeInTheDocument();
    expect(within(board()).getAllByText("Beat median").length).toBeGreaterThan(0);
    expect(within(board()).getAllByText("Missed median").length).toBeGreaterThan(0);
    expect(screen.queryByText("Projected final")).toBeNull();
  });

  it("pending: known scores now, chances named as computing, never 0%", async () => {
    await show(PENDING);
    expect(screen.getByText(/Beat-median chances are still being calculated/)).toBeInTheDocument();
    expect(within(board()).queryByText("0.0%")).toBeNull();
    const top = PENDING.medianRace.teams[0];
    expect(within(rowFor(top.rosterId)).getByText(formatPoints(top.scoreNow))).toBeInTheDocument();
  });

  it("incomplete live scoring: the current median is named unavailable", async () => {
    const p = clone(HALFTIME);
    p.medianRace = { ...p.medianRace, currentMedian: null, currentMedianState: "incomplete_live_scoring" };
    await show(p);
    expect(screen.getByText("Unavailable — live scoring incomplete")).toBeInTheDocument();
    expect(screen.getByText(formatPoints(p.medianRace.projectedMedianMean))).toBeInTheDocument();
  });

  it("a league with no median game shows no percentages at all", async () => {
    const p = clone(HALFTIME);
    p.medianRace = { ...p.medianRace, state: "not_applicable" };
    await show(p);
    expect(screen.getByText(/plays no median game/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /beat the median/ })).toBeNull();
  });
});

describe("Live Median Race — switching and updates", () => {
  it("tapping a row switches Game Day through ?team=", async () => {
    await show(HALFTIME);
    fireEvent.click(within(rowFor("10")).getByRole("button"));
    expect(mockRouter.push).toHaveBeenCalledWith("/game-day?team=owner-10", { scroll: false });
  });

  it("keyboard: a row is a focusable button that Enter activates", async () => {
    await show(HALFTIME);
    const button = within(rowFor("3")).getByRole("button");
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button); // a native <button> fires click on Enter/Space
    expect(mockRouter.push).toHaveBeenCalledWith("/game-day?team=owner-3", { scroll: false });
  });

  it("A -> B -> C: a board tap starts the switch; late answers never overwrite C", async () => {
    // The board is part of each team's answer, so while B loads the reader
    // continues with the picker (or the URL); the request-key guard is what
    // keeps a late B answer from ever landing under C.
    const b = deferred();
    const third = clone(HALFTIME);
    third.team = { ...third.team, ownerId: "owner-3", rosterId: "3" };
    third.medianRace = { ...third.medianRace, selectedRosterId: "3" };
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok(HALFTIME))
      .mockImplementationOnce(() => b.promise)
      .mockResolvedValueOnce(ok(third));
    const view = render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 8/);
    fireEvent.click(within(rowFor("10")).getByRole("button"));
    expect(mockRouter.push).toHaveBeenLastCalledWith("/game-day?team=owner-10", { scroll: false });
    mockSearchParams.value = new Map([["team", "owner-10"]]);
    view.rerender(<GameDayPanel />);
    fireEvent.change(screen.getByRole("combobox", { name: "Viewing team" }), {
      target: { value: "owner-3" },
    });
    mockSearchParams.value = new Map([["team", "owner-3"]]);
    view.rerender(<GameDayPanel />);
    await screen.findByText(/matchup: Team 8 versus/); // third reuses roster 8's hero labels
    await act(async () => b.resolve(ok(OPPONENT)));
    const sel = document.querySelector('[aria-current="true"]');
    expect(sel.closest("li").getAttribute("data-roster-id")).toBe("3");
    expect(rows()).toHaveLength(HALFTIME.leagueTeams.length);
    expect(screen.getByRole("combobox", { name: "Viewing team" })).toHaveValue("owner-3");
  });

  it("a background poll brings a newer generation and the board reorders in place", async () => {
    const gen1 = clone(HALFTIME);
    const gen2 = clone(HALFTIME);
    const [x, y] = [gen2.medianRace.teams[0], gen2.medianRace.teams[1]];
    gen2.medianRace.teams = [
      { ...y, rank: 1, beatMedianPct: 99.5, movementPp: 12.0 },
      { ...x, rank: 2, beatMedianPct: 80.0, movementPp: -18.75 },
      ...gen2.medianRace.teams.slice(2),
    ];
    const poll = deferred();
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok(gen1))
      .mockImplementationOnce(() => poll.promise);
    render(<GameDayPanel />);
    await screen.findByText(`Week ${gen1.week} · ${gen1.season}`);
    expect(rows()[0].getAttribute("data-roster-id")).toBe(x.rosterId);
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    // Polls never overlap: a refresh while one is in flight issues nothing,
    // so an older same-context answer cannot arrive after a newer one.
    fireEvent.click(screen.getByRole("button", { name: /Refresh|Updating/ }));
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    await act(async () => poll.resolve(ok(gen2)));
    expect(rows()[0].getAttribute("data-roster-id")).toBe(y.rosterId);
    expect(within(rows()[0]).getByRole("button").getAttribute("aria-label")).toMatch(/up 12\.0pp/);
  });
});

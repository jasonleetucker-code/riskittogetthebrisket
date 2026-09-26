/**
 * Game Day team switcher (owner directive 2026-09-25, #1335).
 *
 * Game Day must show ANY roster of the selected league from that roster's
 * side. The payloads below are real endpoint output (see
 * game-day-panel.test.jsx): `halftime` is roster 8's side, and
 * `halftime-opponent` is roster 10's side of the SAME collector generation —
 * so the reversed numbers asserted here are the backend's, not a relabel.
 *
 * What is pinned:
 *   - the picker lists exactly the backend's `leagueTeams`, and switching is
 *     a `?team=<ownerId>` push that keeps league / week / season;
 *   - the opponent's side renders the opponent's own numbers;
 *   - a team answered must be the team asked (identity), and a late answer
 *     for an earlier team never publishes (A -> B -> C);
 *   - a team this league does not hold is refused in-league, with no second
 *     request anywhere else;
 *   - URL state: deep link / refresh keep the chosen team, back walks it;
 *   - the picker is a labelled native select that keeps focus across a
 *     switch; the global "my team" is never written.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GameDayPanel from "@/components/GameDayPanel";
import { formatPct, formatPoints, whatMattersNow } from "@/lib/game-day-view";

import HALFTIME from "../fixtures/game-day/halftime.json";
import OPPONENT from "../fixtures/game-day/halftime-opponent.json";
import PENDING from "../fixtures/game-day/pending.json";

const mockUserState = { state: { selectedTeam: null } };
vi.mock("@/components/useUserState", () => ({
  useUserState: () => mockUserState,
}));

const mockSearchParams = { value: new Map() };
const mockRouter = { push: vi.fn() };
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams.value,
  useRouter: () => mockRouter,
  usePathname: () => "/game-day",
}));

const mockLeague = { selectedLeagueKey: "dynasty_main", loading: false };
vi.mock("@/components/useLeague", () => ({
  useLeague: () => mockLeague,
}));

const MINE = "owner-8";
const clone = (x) => JSON.parse(JSON.stringify(x));

/**
 * LABELLED SYNTHETIC: roster 8's real payload re-keyed to another owner,
 * used ONLY where a test needs a third distinct identity (A -> B -> C,
 * non-owner -> non-owner). Its numbers are not asserted as that team's.
 */
function asOwner(ownerId, base = HALFTIME) {
  const p = clone(base);
  const t = p.leagueTeams.find((x) => x.ownerId === ownerId);
  p.team = { ...p.team, ownerId, rosterId: t.rosterId, displayName: t.displayName, teamName: t.teamName };
  return p;
}

function ok(body) {
  return { ok: true, status: 200, json: async () => body };
}

function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

function picker() {
  return screen.getByRole("combobox", { name: "Viewing team" });
}

function heroTable() {
  return screen.getByRole("table", { name: /matchup:/ });
}

/** Simulate Next applying a pushed URL: new search params, re-render. */
function navigate(view, params) {
  mockSearchParams.value = new Map(Object.entries(params));
  view.rerender(<GameDayPanel />);
}

beforeEach(() => {
  mockUserState.state = { selectedTeam: { ownerId: MINE, name: "Replay roster 8" } };
  mockSearchParams.value = new Map();
  mockRouter.push = vi.fn();
  mockLeague.selectedLeagueKey = "dynasty_main";
  mockLeague.loading = false;
  globalThis.fetch = vi.fn(async () => ok(HALFTIME));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Game Day team switcher — the list and the default", () => {
  it("opens on the user's team and lists exactly the league's rosters", async () => {
    render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    expect(globalThis.fetch.mock.calls[0][0]).toContain(`team=${MINE}`);
    const select = picker();
    expect(select).toHaveValue(MINE);
    const options = within(select).getAllByRole("option");
    expect(options.map((o) => o.value)).toEqual(HALFTIME.leagueTeams.map((t) => t.ownerId));
    expect(within(select).getByRole("option", { selected: true }).textContent).toMatch(
      /Replay roster 8 — Team 8 \(your team\)/,
    );
    // The scheduled opponent is marked relative to the team being viewed.
    expect(within(select).getByRole("option", { name: /Replay roster 10.*\(opponent\)/ })).toBeTruthy();
  });

  it("uses the server's default team when the session names none", async () => {
    mockUserState.state = { selectedTeam: null };
    render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    expect(globalThis.fetch.mock.calls[0][0]).not.toContain("team=");
    // The picker shows whoever the backend answered for.
    expect(picker()).toHaveValue(HALFTIME.team.ownerId);
    expect(screen.queryByRole("button", { name: "Back to my team" })).toBeNull();
  });
});

describe("Game Day team switcher — switching", () => {
  it("pushes ?team= and keeps league, week and season", async () => {
    mockSearchParams.value = new Map([
      ["leagueKey", "dynasty_main"],
      ["week", "3"],
      ["season", "2026"],
    ]);
    render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    fireEvent.change(picker(), { target: { value: "owner-10" } });
    expect(mockRouter.push).toHaveBeenCalledTimes(1);
    const [url, opts] = mockRouter.push.mock.calls[0];
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(url.startsWith("/game-day?")).toBe(true);
    expect(Object.fromEntries(qs)).toEqual({
      leagueKey: "dynasty_main",
      week: "3",
      season: "2026",
      team: "owner-10",
    });
    expect(opts).toEqual({ scroll: false });
  });

  it("renders the selected opponent's OWN side, not my payload relabelled", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    const mineWin = formatPct(HALFTIME.team.outcome.winMatchupPct);
    const theirWin = formatPct(OPPONENT.team.outcome.winMatchupPct);
    expect(mineWin).not.toBe(theirWin);
    globalThis.fetch.mockResolvedValueOnce(ok(OPPONENT));
    navigate(view, { team: "owner-10" });
    await screen.findByText(/Week 3 matchup: Team 10 versus Team 8/);
    expect(globalThis.fetch.mock.calls.at(-1)[0]).toContain("team=owner-10");
    const selectedRow = within(heroTable()).getByRole("row", { name: /Team 10/ });
    expect(within(selectedRow).getByText(theirWin)).toBeInTheDocument();
    expect(picker()).toHaveValue("owner-10");
    expect(document.querySelector("[data-game-day-team]")).toHaveAttribute(
      "data-game-day-team",
      "owner-10",
    );
    // Viewing a rival offers the way back without touching global state.
    fireEvent.click(screen.getByRole("button", { name: "Back to my team" }));
    expect(mockRouter.push).toHaveBeenLastCalledWith(`/game-day?team=${MINE}`, { scroll: false });
  });

  it("switches between two teams that are not the user's", async () => {
    globalThis.fetch = vi.fn(async () => ok(OPPONENT));
    mockSearchParams.value = new Map([["team", "owner-10"]]);
    const view = render(<GameDayPanel />);
    await screen.findByText(/Week 3 matchup: Team 10/);
    globalThis.fetch.mockResolvedValueOnce(ok(asOwner("owner-3")));
    navigate(view, { team: "owner-3" });
    await screen.findByText(/Week 3 matchup: Team 3/);
    expect(globalThis.fetch.mock.calls.at(-1)[0]).toContain("team=owner-3");
    expect(picker()).toHaveValue("owner-3");
    expect(screen.queryByText(/matchup: Team 10/)).toBeNull();
  });

  it("keeps the picker mounted and focused while the next team loads", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    const select = picker();
    select.focus();
    const later = deferred();
    globalThis.fetch.mockImplementationOnce(() => later.promise);
    navigate(view, { team: "owner-10" });
    // Loading names the team being loaded; no Team 8 numbers remain.
    expect(screen.getByText("Loading Replay roster 10's matchup...")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /matchup:/ })).toBeNull();
    expect(picker()).toBe(select);
    expect(document.activeElement).toBe(select);
    expect(select).toHaveValue("owner-10");
    await act(async () => later.resolve(ok(OPPONENT)));
    expect(await screen.findByText(/matchup: Team 10/)).toBeInTheDocument();
    expect(document.activeElement).toBe(select);
  });

  it("closes detail sections opened for the previous team", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    fireEvent.click(screen.getByRole("button", { name: "Best-ball details" }));
    expect(screen.getByRole("button", { name: "Best-ball details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    globalThis.fetch.mockResolvedValueOnce(ok(OPPONENT));
    navigate(view, { team: "owner-10" });
    await screen.findByText(/matchup: Team 10/);
    expect(screen.getByRole("button", { name: "Best-ball details" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("shows a newly selected team's PENDING forecast as computing", async () => {
    globalThis.fetch = vi.fn(async () => ok(OPPONENT));
    mockSearchParams.value = new Map([["team", "owner-10"]]);
    const view = render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 10/);
    globalThis.fetch.mockResolvedValueOnce(ok(PENDING));
    navigate(view, { team: PENDING.team.ownerId });
    // The cold capture carries no manager names, so the host's roster label.
    await screen.findByText(new RegExp(`matchup: ${PENDING.team.displayName} versus`));
    expect(picker()).toHaveValue(PENDING.team.ownerId);
    expect(within(heroTable()).getAllByText(/Computing/).length).toBeGreaterThan(0);
    // Known facts are shown now; nothing forecast is rendered as a number.
    expect(within(heroTable()).queryByText("0%")).toBeNull();
  });
});

describe("Game Day team switcher — identity and races", () => {
  it("refuses an answer for a different team than the one asked", async () => {
    globalThis.fetch = vi.fn(async () => ok(HALFTIME)); // owner-8's side
    mockSearchParams.value = new Map([["team", "owner-10"]]);
    const view = render(<GameDayPanel />);
    expect(await screen.findByText("The matchup response is incomplete. Please retry.")).toBeInTheDocument();
    expect(view.container.querySelector('[data-game-day-ready="true"]')).toBeNull();
    expect(screen.queryByText(/matchup: Team 8/)).toBeNull();
  });

  it("A -> B -> C: late A and B answers never publish under C", async () => {
    const a = deferred();
    const b = deferred();
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok(HALFTIME))
      .mockImplementationOnce(() => a.promise)
      .mockImplementationOnce(() => b.promise)
      .mockResolvedValueOnce(ok(asOwner("owner-3")));
    const view = render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 8/);
    navigate(view, { team: "owner-10" }); // A
    const signalA = globalThis.fetch.mock.calls[1][1].signal;
    navigate(view, { team: "owner-1" }); // B
    const signalB = globalThis.fetch.mock.calls[2][1].signal;
    navigate(view, { team: "owner-3" }); // C
    await screen.findByText(/matchup: Team 3/);
    expect(signalA.aborted).toBe(true);
    expect(signalB.aborted).toBe(true);
    // A transport that ignores abort still cannot publish.
    await act(async () => a.resolve(ok(OPPONENT)));
    await act(async () => b.resolve(ok(asOwner("owner-1"))));
    expect(screen.getByText(/matchup: Team 3/)).toBeInTheDocument();
    expect(screen.queryByText(/matchup: Team 10/)).toBeNull();
    expect(screen.queryByText(/matchup: Team 1 /)).toBeNull();
    expect(picker()).toHaveValue("owner-3");
    expect(globalThis.fetch.mock.calls.map((c) => new URL(c[0], "http://x").searchParams.get("team"))).toEqual(
      [MINE, "owner-10", "owner-1", "owner-3"],
    );
  });
});

describe("Game Day team switcher — league isolation", () => {
  it("refuses a team this league does not hold, offering this league's teams only", async () => {
    const teams = HALFTIME.leagueTeams;
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({
        error: "team_not_found",
        leagueKey: "dynasty_main",
        requestedTeam: "owner-of-another-league",
        leagueTeams: teams,
      }),
    }));
    mockSearchParams.value = new Map([["team", "owner-of-another-league"]]);
    render(<GameDayPanel />);
    expect(await screen.findByText("That team is not in this league")).toBeInTheDocument();
    // Exactly one request, to the selected league — no fallback anywhere.
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const qs = new URL(globalThis.fetch.mock.calls[0][0], "http://x").searchParams;
    expect(qs.get("leagueKey")).toBe("dynasty_main");
    expect(qs.get("team")).toBe("owner-of-another-league");
    const select = picker();
    expect(select).toHaveValue("");
    expect(within(select).getAllByRole("option").slice(1).map((o) => o.value)).toEqual(
      teams.map((t) => t.ownerId),
    );
    fireEvent.change(select, { target: { value: "owner-4" } });
    expect(mockRouter.push).toHaveBeenCalledWith("/game-day?team=owner-4", { scroll: false });
  });

  it("a session with no team of its own is offered the league's teams, not a default", async () => {
    mockUserState.state = { selectedTeam: null };
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({
        error: "team_required",
        leagueKey: "dynasty_main",
        leagueTeams: HALFTIME.leagueTeams,
      }),
    }));
    render(<GameDayPanel />);
    expect(await screen.findByText("No team selected")).toBeInTheDocument();
    expect(screen.getByText("Choose any team in this league above to see its Game Day.")).toBeInTheDocument();
    expect(picker()).toHaveValue("");
    expect(screen.queryByRole("table", { name: /matchup:/ })).toBeNull();
    fireEvent.change(picker(), { target: { value: "owner-10" } });
    expect(mockRouter.push).toHaveBeenCalledWith("/game-day?team=owner-10", { scroll: false });
  });

  it("does not adopt a refusal's team list from a different league", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({
        error: "team_not_found",
        leagueKey: "dynasty_new",
        leagueTeams: HALFTIME.leagueTeams,
      }),
    }));
    mockSearchParams.value = new Map([["team", "owner-zzz"]]);
    render(<GameDayPanel />);
    expect(await screen.findByText("That team is not in this league")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Viewing team" })).toBeNull();
  });

  it("drops the previous league's teams the moment the league changes", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    expect(picker()).toBeInTheDocument();
    globalThis.fetch.mockImplementationOnce(() => new Promise(() => {}));
    mockLeague.selectedLeagueKey = "dynasty_new";
    view.rerender(<GameDayPanel />);
    expect(screen.queryByRole("combobox", { name: "Viewing team" })).toBeNull();
    expect(screen.getByText("Loading this week's matchup...")).toBeInTheDocument();
  });
});

describe("Game Day team switcher — URL state", () => {
  it("a deep link or refresh opens the linked team, not my team", async () => {
    globalThis.fetch = vi.fn(async () => ok(OPPONENT));
    mockSearchParams.value = new Map([["team", "owner-10"]]);
    render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 10/);
    expect(globalThis.fetch.mock.calls[0][0]).toContain("team=owner-10");
    expect(globalThis.fetch.mock.calls[0][0]).not.toContain(`team=${MINE}`);
  });

  it("back to the previous URL restores the previous team", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 8/);
    globalThis.fetch.mockResolvedValueOnce(ok(OPPONENT));
    navigate(view, { team: "owner-10" });
    await screen.findByText(/matchup: Team 10/);
    globalThis.fetch.mockResolvedValueOnce(ok(HALFTIME));
    navigate(view, {}); // browser back to /game-day
    await screen.findByText(/matchup: Team 8/);
    expect(picker()).toHaveValue(MINE);
    expect(globalThis.fetch.mock.calls.at(-1)[0]).toContain(`team=${MINE}`);
  });
});

describe("Game Day team switcher — accessibility", () => {
  it("is a labelled, described native select", async () => {
    render(<GameDayPanel />);
    await screen.findByText("Week 3 · 2026");
    const select = picker();
    expect(select.tagName).toBe("SELECT");
    expect(select).toHaveAccessibleDescription(/Any team in this league/);
    // An unmanaged roster would be listed but not choosable.
    expect(within(select).getAllByRole("option").every((o) => !o.disabled)).toBe(true);
  });
});

describe("Game Day team switcher — the whole page is the selected team's", () => {
  function mattersText() {
    const heading = screen.getByRole("heading", { name: "What matters now" });
    return heading.closest("section").textContent;
  }

  it("What matters now and the score are the selected roster's own", async () => {
    const view = render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 8/);
    const mine = whatMattersNow(HALFTIME);
    const theirs = whatMattersNow(OPPONENT);
    // The two perspectives genuinely differ (backend leverage and lineup
    // odds per side), so this cannot pass on a relabelled payload.
    expect(theirs.map((i) => i.detail)).not.toEqual(mine.map((i) => i.detail));
    for (const item of mine) expect(mattersText()).toContain(item.detail);

    globalThis.fetch.mockResolvedValueOnce(ok(OPPONENT));
    navigate(view, { team: "owner-10" });
    await screen.findByText(/matchup: Team 10/);
    for (const item of theirs) expect(mattersText()).toContain(item.detail);
    for (const item of mine.filter((i) => !theirs.some((t) => t.detail === i.detail))) {
      expect(mattersText()).not.toContain(item.detail);
    }
    // Score now belongs to roster 10: its best-ball 3.8, and the host's
    // literal 0 is shown as a real zero ("Sleeper shows 0.0"), not missing.
    const row = within(heroTable()).getByRole("row", { name: /Team 10/ });
    expect(within(row).getByText(formatPoints(OPPONENT.team.scoreNow.bestBallFromBankedPoints))).toBeInTheDocument();
    expect(within(row).getByText("Sleeper shows 0.0")).toBeInTheDocument();
  });

  it("identity is the ownerId, so a cosmetic rename keeps the selection", async () => {
    const renamed = clone(OPPONENT);
    for (const t of renamed.leagueTeams) t.teamName = `${t.teamName} (renamed)`;
    renamed.team.teamName = `${renamed.team.teamName} (renamed)`;
    globalThis.fetch = vi.fn().mockResolvedValueOnce(ok(OPPONENT)).mockResolvedValue(ok(renamed));
    mockSearchParams.value = new Map([["team", "owner-10"]]);
    render(<GameDayPanel />);
    await screen.findByText(/matchup: Team 10/);
    fireEvent.click(screen.getByRole("button", { name: /Refresh/ }));
    await screen.findByRole("option", { name: /Replay roster 10 \(renamed\)/ });
    expect(picker()).toHaveValue("owner-10");
    expect(globalThis.fetch.mock.calls.every((c) => c[0].includes("team=owner-10"))).toBe(true);
  });

  it("switching away from a computing team: its later poll never lands on the new team", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      globalThis.fetch = vi.fn(async () => ok(PENDING)); // owner-8, forecast computing
      const view = render(<GameDayPanel />);
      await screen.findByText(/matchup: Roster 8 versus/);
      const later = deferred();
      globalThis.fetch.mockImplementationOnce(() => later.promise);
      navigate(view, { team: "owner-10" });
      // Past the 10 s pending re-poll the old team would have scheduled.
      await act(async () => {
        vi.advanceTimersByTime(15_000);
      });
      const teams = globalThis.fetch.mock.calls.map((c) => new URL(c[0], "http://x").searchParams.get("team"));
      expect(teams.slice(1).every((t) => t === "owner-10")).toBe(true);
      await act(async () => later.resolve(ok(OPPONENT)));
      expect(await screen.findByText(/matchup: Team 10 versus Team 8/)).toBeInTheDocument();
      expect(screen.queryByText(/matchup: Roster 8/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

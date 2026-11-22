/**
 * The home "This week" panel (DYN10 #5): ThisWeekPanel (fetch + lazy mount)
 * and ThisWeekPlan (body), rendered from payloads produced by the REAL
 * composer (fixtures pinned by tests/api/test_team_plan_frontend_fixtures.py).
 *
 * Pins: one request per (league, team), held until identity settles; NOTHING
 * renders — not even an empty card — on 503 (flag off, the production
 * default), 401, 404, a network error, a league out of scope or an answer for
 * another team; a plan renders its actions in the payload's order; unavailable
 * sections and the incomplete state carry their reasons; stale rosters warn;
 * no missing value renders as 0; every state is text, not colour alone.
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";

const team = vi.hoisted(() => ({
  value: {
    selectedTeam: { ownerId: "o0", name: "Team o0" },
    selectedLeagueKey: "dynasty_main",
    leagueLoading: false,
    loading: false,
  },
}));
vi.mock("@/components/useTeam", () => ({ useTeam: () => team.value }));

import ThisWeekPanel from "@/components/terminal/ThisWeekPanel";
import ThisWeekPlan from "@/components/terminal/ThisWeekPlan";

const load = (name) =>
  JSON.parse(
    fs.readFileSync(path.resolve(__dirname, `../fixtures/team-plan/${name}.json`), "utf-8"),
  );
const ACTIONS = load("plan-actions");
const INCOMPLETE = load("plan-incomplete-stale");
const DO_NOTHING = load("plan-do-nothing");

const STANDALONE_ZERO = /(?<![\w.,$])\$?0(?![\w.,])/;

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setTeam(overrides) {
  team.value = {
    selectedTeam: { ownerId: "o0", name: "Team o0" },
    selectedLeagueKey: "dynasty_main",
    leagueLoading: false,
    loading: false,
    ...overrides,
  };
}

beforeEach(() => {
  setTeam({});
});
afterEach(() => {
  vi.unstubAllGlobals();
});

// Several macrotask turns: the fetch, the JSON body and the lazy chunk.
async function settle() {
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function renderPanelWith(response) {
  const fetchMock = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<ThisWeekPanel />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  // Let the response settle before asserting on what rendered.
  await act(async () => {
    await Promise.resolve();
  });
  return { ...view, fetchMock };
}

describe("ThisWeekPanel — request and silence", () => {
  it("requests the selected team's plan once, with league and team", async () => {
    const { fetchMock } = await renderPanelWith(jsonResponse(ACTIONS));
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/team/plan?leagueKey=dynasty_main&team=o0");
    expect(options.credentials).toBe("same-origin");
    expect(await screen.findByTestId("this-week-plan")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not refetch on re-render, and fetches again only for a new team", async () => {
    const { fetchMock, rerender } = await renderPanelWith(jsonResponse(ACTIONS));
    await screen.findByTestId("this-week-plan");
    rerender(<ThisWeekPanel />);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ error: "x" }, 404)));
    setTeam({ selectedTeam: { ownerId: "o1", name: "Team o1" } });
    rerender(<ThisWeekPanel />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/team/plan?leagueKey=dynasty_main&team=o1");
    // The previous team's plan never shows under the new team.
    await waitFor(() => expect(screen.queryByTestId("this-week-plan")).toBeNull());
  });

  it("holds the request until league and team identity settle", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setTeam({ loading: true });
    const { container, rerender } = render(<ThisWeekPanel />);
    setTeam({ leagueLoading: true });
    rerender(<ThisWeekPanel />);
    setTeam({ selectedTeam: null });
    rerender(<ThisWeekPanel />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["503 flag off", () => jsonResponse({ error: "feature_disabled", flag: "team_advisor_plan" }, 503)],
    ["503 data not ready", () => jsonResponse({ error: "data_not_ready" }, 503)],
    ["401 signed out", () => jsonResponse({ error: "auth_required" }, 401)],
    ["404 unknown team", () => jsonResponse({ error: "team_not_found" }, 404)],
    ["404 no route", () => new Response("Not Found", { status: 404 })],
    ["network error", () => new TypeError("Failed to fetch")],
    [
      "league out of scope",
      () =>
        jsonResponse({
          contractVersion: ACTIONS.contractVersion,
          available: false,
          unavailableReason: "league_not_in_scope",
          leagueKey: "dynasty_main",
        }),
    ],
    ["a plan for another team", () => jsonResponse({ ...ACTIONS, team: { ...ACTIONS.team, ownerId: "o9" } })],
    ["a plan for another league", () => jsonResponse({ ...ACTIONS, leagueKey: "dynasty_new" })],
  ])("renders nothing on %s", async (_label, make) => {
    const { container } = await renderPanelWith(make());
    await settle();
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("This week")).toBeNull();
  });

  it("control: the same harness and wait DO show a served plan", async () => {
    // Proves the silence cases above are not vacuous: given the identical
    // fetch -> settle sequence, an accepted plan (lazy chunk included) renders.
    await renderPanelWith(jsonResponse(ACTIONS));
    await settle();
    expect(screen.queryByTestId("this-week-plan")).not.toBeNull();
  });
});

describe("ThisWeekPlan — a served plan", () => {
  it("renders the actions in the payload's order with text kind labels", () => {
    render(<ThisWeekPlan plan={ACTIONS} />);
    expect(screen.getByRole("heading", { name: "This week" })).toBeInTheDocument();
    expect(screen.getByText("Team o0 · advisory plan, not a verdict")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Next moves, in the plan's order" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(ACTIONS.actions.length);
    const rendered = items.map((li) => li.textContent);
    expect(rendered[0]).toMatch(/^1\.Buy targetPlayer t1 \(WR\)/);
    expect(rendered[1]).toMatch(/^2\.Sell highGive A for B/);
    expect(rendered[2]).toMatch(/^3\.Waiver moveAdd FA w1 \(LB\), release Rel \(LB\)/);
    expect(rendered[3]).toMatch(/^4\.Aging roomQB room is older than league peers/);
    expect(rendered[4]).toMatch(/^5\.Buy targetPlayer t2 \(WR\)/);
    expect(rendered[5]).toMatch(/^6\.Waiver moveAdd FA w2/);
    expect(rendered[6]).toMatch(/^7\.Waiver moveAdd FA w3/);
  });

  it("shows each action's reason, uncertainty and owner", () => {
    render(<ThisWeekPlan plan={ACTIONS} />);
    const items = within(screen.getByRole("list", { name: /Next moves/ })).getAllByRole("listitem");
    const buy = items[0];
    expect(buy).toHaveTextContent(ACTIONS.actions[0].reason);
    expect(buy).toHaveTextContent("Confidence: 0.5 · Market edge: not measured · Availability: not measured");
    expect(buy).toHaveTextContent("Evidence · Gameplan targets");
    expect(buy).toHaveTextContent(`Computed by${ACTIONS.actions[0].owner}`);
  });

  it("renders the context rows", () => {
    render(<ThisWeekPlan plan={ACTIONS} />);
    const ctx = screen.getByLabelText("Team context");
    expect(ctx).toHaveTextContent("PosturePUSH (a classification, not a verdict)");
    expect(ctx).toHaveTextContent("Team strengthRank 2 of 4");
    expect(ctx).toHaveTextContent("Weak spotsTE (high)");
    expect(ctx).toHaveTextContent("Draft capital2027 class $100; all classes $300");
    expect(ctx).toHaveTextContent("RostersCurrent, fetched 1 hour ago");
    expect(screen.queryByText("Rosters are stale")).toBeNull();
    expect(screen.queryByText("Plan incomplete")).toBeNull();
    expect(screen.getByText(/Pick moves are not assessed/)).toBeInTheDocument();
  });
});

describe("ThisWeekPlan — honest states", () => {
  it("shows unavailable sections and the incomplete state with their reasons", () => {
    render(<ThisWeekPlan plan={INCOMPLETE} />);
    const ctx = screen.getByLabelText("Team context");
    expect(ctx).toHaveTextContent(
      "Posturenot available yet (the league analysis has not been built yet)",
    );
    expect(ctx).toHaveTextContent(
      "Draft capitalnot available yet (the draft-capital board has not been built yet)",
    );
    const banner = screen.getByText("Plan incomplete").closest(".ds-banner");
    expect(banner).toHaveTextContent("not “nothing to do”");
    expect(banner).toHaveTextContent(
      "Buy target: not available yet (trade targets have not been built for this team yet)",
    );
    expect(banner).toHaveTextContent(
      "Waiver move: not available yet (Perfect Waivers has not run for this team recently)",
    );
    expect(banner).toHaveTextContent(
      "Aging room: only partly assessed (DB: age versus the league median could not be measured)",
    );
    expect(screen.queryByRole("list", { name: /Next moves/ })).toBeNull();
    expect(screen.getByText(/No move to show yet/)).toBeInTheDocument();
  });

  it("warns, as text, when rosters are stale", () => {
    render(<ThisWeekPlan plan={INCOMPLETE} />);
    const alert = screen
      .getAllByRole("alert")
      .find((el) => el.textContent.includes("Rosters are stale"));
    expect(alert).toBeTruthy();
    expect(alert).toHaveTextContent(
      "This plan reads rosters fetched 30.5 hours ago, from the last good snapshot.",
    );
    expect(screen.getByLabelText("Team context")).toHaveTextContent(
      "RostersStale, fetched 30.5 hours ago, from the last good snapshot",
    );
  });

  it("warns when roster freshness is unknown", () => {
    const plan = { ...ACTIONS, rosterFreshness: { state: "unknown", source: null, fetchedAt: null, ageHours: null } };
    render(<ThisWeekPlan plan={plan} />);
    expect(screen.getByText("Roster freshness unknown")).toBeInTheDocument();
  });

  it("never renders a missing value as 0", () => {
    const { container, unmount } = render(<ThisWeekPlan plan={INCOMPLETE} />);
    expect(container.textContent).not.toMatch(STANDALONE_ZERO);
    expect(screen.getByLabelText("Team context")).toHaveTextContent(
      "Team strengthleague rank not available",
    );
    expect(screen.getByLabelText("Team context")).toHaveTextContent(
      "Core agenot available (unmeasured)",
    );
    unmount();

    const unpriced = {
      ...ACTIONS,
      rosterFreshness: { state: "unknown", source: null, fetchedAt: null, ageHours: null },
      draftCapital: {
        ...ACTIONS.draftCapital,
        teamTotalsState: "unavailable",
        teamTotalsReason: "upcoming_class_unpriced",
        upcomingClass: { ...ACTIONS.draftCapital.upcomingClass, auctionDollars: null },
        allYears: { ...ACTIONS.draftCapital.allYears, auctionDollars: null },
      },
      actions: [
        {
          ...ACTIONS.actions[0],
          evidence: { lineupGain: null, priority: null },
          uncertainty: { confidence: null, marketEdge: null },
        },
      ],
    };
    render(<ThisWeekPlan plan={unpriced} />);
    const ctx = screen.getByLabelText("Team context");
    expect(ctx).toHaveTextContent("Auction budgets unavailable");
    expect(ctx.textContent.replace("Not shown as $0.", "")).not.toMatch(STANDALONE_ZERO);
    const item = within(screen.getByRole("list", { name: /Next moves/ })).getByRole("listitem");
    expect(item).toHaveTextContent("Confidence: not measured · Market edge: not measured");
    expect(item).toHaveTextContent("Lineup gainnot available");
    expect(item.textContent).not.toMatch(STANDALONE_ZERO);
  });

  it("renders do_nothing as its own stated move", () => {
    render(<ThisWeekPlan plan={DO_NOTHING} />);
    const item = within(screen.getByRole("list", { name: /Next moves/ })).getByRole("listitem");
    expect(item).toHaveTextContent("No move");
    expect(item).toHaveTextContent("Hold: no move cleared any assessed check");
    expect(item).toHaveTextContent("Not assessed: Pick move");
  });
});

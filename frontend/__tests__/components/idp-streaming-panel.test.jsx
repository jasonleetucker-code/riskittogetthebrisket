/**
 * /waiver-advisor — the "Weekly IDP streaming" mode (owner directive 2026-10-29).
 *
 * Fixtures are the REAL composer's output (tests/waivers/streaming_ui_payloads.py,
 * byte-pinned by tests/waivers/test_streaming_ui_fixtures.py).  Pins: the mode
 * exists only when the backend gate answers; it sends the selected league,
 * team and controls; it renders the backend's plan, alternatives, larger-budget
 * plan, capacity curve, streaming board and safe-to-drop board without
 * computing anything; the explicit no-move state, a bounded solve and every
 * failure code are stated in words; a missing value is never 0.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import recommend from "../fixtures/idp-streaming/recommend.json";
import budgetLimited from "../fixtures/idp-streaming/budget-limited.json";
import noMove from "../fixtures/idp-streaming/no-move.json";
import bounded from "../fixtures/idp-streaming/bounded.json";
import budgetBinds from "../fixtures/idp-streaming/budget-binds.json";

vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: { key: "dynasty_main", idpEnabled: true } }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: { ownerId: "owner-me", name: "Mine" }, loading: false }),
}));
vi.mock("@/components/TeamSwitcher", () => ({ default: () => <div data-testid="team-switcher" /> }));

import WaiverAdvisorPage from "@/app/waiver-advisor/page";

const ADVISOR = {
  version: "waiver-advisor/2026-10-27.v1",
  leagueKey: "dynasty_main",
  team: { ownerId: "owner-me", name: "Mine" },
  candidates: [],
  census: { shown: 0, matchingFilter: 0 },
  faab: { state: "known", remaining: 62, bidMethodology: "market_aware" },
  posture: { state: "unavailable", reason: "league_bundle_not_warm" },
  plan: null,
  methodologyDependencies: [],
  notes: [],
};

function respond(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

/** Route fetch by URL; `streaming(body)` answers the streaming endpoint. */
function mockFetch(streaming) {
  global.fetch = vi.fn(async (url, init) => {
    const body = JSON.parse(init?.body || "{}");
    if (url === "/api/waiver/advisor") return respond(200, ADVISOR);
    if (url === "/api/waiver/streaming") {
      if (!body.teamOwnerId) return respond(400, { error: "team_required", leagueKey: "dynasty_main" });
      return streaming(body);
    }
    return respond(404, {});
  });
}

function streamingCalls() {
  return global.fetch.mock.calls
    .filter(([u, init]) => u === "/api/waiver/streaming" && JSON.parse(init.body).teamOwnerId)
    .map(([, init]) => JSON.parse(init.body));
}

async function openStreaming() {
  render(<WaiverAdvisorPage />);
  const radio = await screen.findByRole("radio", { name: "Weekly IDP streaming" });
  await waitFor(() => expect(radio).not.toBeDisabled());
  fireEvent.click(radio);
  return screen.findByTestId("idp-streaming");
}

describe("/waiver-advisor — Weekly IDP streaming mode", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("has no streaming mode while its flag is off", async () => {
    global.fetch = vi.fn(async (url) =>
      url === "/api/waiver/streaming"
        ? respond(503, { error: "feature_disabled", flag: "idp_streaming" })
        : respond(200, ADVISOR),
    );
    render(<WaiverAdvisorPage />);
    await screen.findByTestId("waiver-advisor");
    await waitFor(() =>
      expect(global.fetch.mock.calls.some(([u]) => u === "/api/waiver/streaming")).toBe(true),
    );
    expect(screen.queryByRole("radio", { name: "Weekly IDP streaming" })).toBeNull();
  });

  it("sends the selected league and team with the default controls", async () => {
    mockFetch(() => respond(200, budgetLimited));
    await openStreaming();
    await waitFor(() => expect(streamingCalls().length).toBeGreaterThan(0));
    expect(streamingCalls()[0]).toEqual({
      leagueKey: "dynasty_main",
      teamOwnerId: "owner-me",
      horizonWeeks: 1,
      position: "ALL",
      dynastyBudget: 0,
    });
    // No capacity was sent; the control shows the one the backend applied.
    await waitFor(() =>
      expect(screen.getByLabelText("Streaming capacity")).toHaveValue(
        String(budgetLimited.request.capacity),
      ),
    );
    // The advisor's own request is not re-run while streaming is showing.
    const advisorCalls = global.fetch.mock.calls.filter(([u]) => u === "/api/waiver/advisor").length;
    expect(advisorCalls).toBe(1);
  });

  it("renders the backend's plan, its numbers and the reasoning", async () => {
    mockFetch(() => respond(200, recommend));
    await openStreaming();
    const rec = await screen.findByTestId("streaming-recommendation");
    expect(within(rec).getByText(/Weekly lineup gain/)).toBeInTheDocument();
    expect(within(rec).getByText(`+${recommend.plan.weeklyGainPoints.toFixed(1)} pts`)).toBeInTheDocument();
    // Partial dynasty change is stated, never presented as complete.
    expect(
      within(rec).getByText("Unknown — 1 added player unvalued (known part +850)"),
    ).toBeInTheDocument();
    // The release-cost basis travels with each drop, and the week rule is stated.
    expect(within(rec).getByTestId("streaming-moves")).toHaveTextContent(
      "value above the replacement free agent",
    );
    expect(screen.getAllByText(/next week — waiver days/).length).toBeGreaterThan(0);
    expect(within(rec).getByText("dynasty value charged against your budget")).toBeInTheDocument();
    expect(within(rec).getByTestId("streaming-gain-by-week")).toHaveTextContent("Week 9");
    const moves = within(rec).getByTestId("streaming-moves");
    expect(moves).toHaveTextContent("Nick Lambright");
    expect(moves).toHaveTextContent("Elijah Banks");
    expect(moves).toHaveTextContent("Off the dynasty board — $0 claim only");
    expect(screen.getAllByText(/Optimal — proven best/).length).toBeGreaterThan(0);
    // Unprojected roster defender is warned about, not zeroed.
    expect(screen.getByText("Roster defenders without a projection").parentElement).toHaveTextContent(
      /Sam Okafor \(week 9, 10\) — no weekly projection/,
    );
    // Alternatives and capacity curve.
    expect(screen.getByRole("table", { name: /Alternative add\/drop/ })).toHaveTextContent(
      "Add Nick Lambright · Drop Elijah Banks",
    );
    const curve = screen.getByTestId("streaming-capacity-curve");
    expect(within(curve).getByText("Recommended")).toBeInTheDocument();
    expect(within(curve).getAllByRole("img").length).toBe(recommend.capacityCurve.length);
    // Posture is context only.
    expect(screen.getByText(/context only — never raises the dynasty budget/)).toBeInTheDocument();
  });

  it("ranks the streaming board on the backend's order and states unknowns", async () => {
    mockFetch(() => respond(200, recommend));
    await openStreaming();
    const board = await screen.findByRole("table", { name: /Available IDP players/ });
    const rows = within(board).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(
      recommend.streamingBoard.map((b) => expect.stringContaining(b.name)),
    );
    // An off-board free agent's dynasty value is "Unknown", never 0.
    const gaines = rows.find((r) => r.textContent.includes("Tyrell Gaines"));
    expect(gaines).toHaveTextContent("Unknown");
    // A player with no week-9 projection shows his state.
    const mendel = rows.find((r) => r.textContent.includes("Bryce Mendel"));
    expect(mendel).toHaveTextContent("— no projection");
    // His weighted projection is unknown (one horizon week missing), with the known part.
    expect(mendel).toHaveTextContent("Unknown (1 week unprojected · known part 6.0)");
    // Expanding a row shows the week-by-week sources and coverage.
    fireEvent.click(within(rows[0]).getByRole("button", { expanded: false }));
    expect(await screen.findAllByText(/sleeper_weekly · 75% of paid categories/)).not.toHaveLength(0);
  });

  it("classifies the roster and explains protection", async () => {
    mockFetch(() => respond(200, recommend));
    await openStreaming();
    const table = await screen.findByRole("table", { name: /classified by drop safety/ });
    expect(table).toHaveTextContent("Churn");
    expect(table).toHaveTextContent("Conditional");
    expect(table).toHaveTextContent("Protected");
    const ross = within(table)
      .getAllByRole("row")
      .find((r) => r.textContent.includes("Jaylen Ross"));
    fireEvent.click(within(ross).getByRole("button", { expanded: false }));
    expect(await screen.findByText("Why he is protected")).toBeInTheDocument();
    expect(screen.getAllByText(/developmental asset/).length).toBeGreaterThan(1);
    expect(screen.getByText(/Development: rising snap share/)).toBeInTheDocument();
    // A conditional player's release is charged at full value, and says why.
    const okafor = within(table)
      .getAllByRole("row")
      .find((r) => r.textContent.includes("Sam Okafor"));
    fireEvent.click(within(okafor).getByRole("button", { expanded: false }));
    expect(
      await screen.findByText(
        /Release cost basis: conditional: full value — the drop assessment says a free release is unsafe/,
      ),
    ).toBeInTheDocument();
  });

  it("shows what a larger dynasty budget would buy", async () => {
    mockFetch(() => respond(200, budgetLimited));
    await openStreaming();
    const lb = await screen.findByTestId("streaming-larger-budget");
    expect(lb).toHaveTextContent("Add Nick Lambright, Tyrell Gaines");
  });

  it("states an explicit no-move recommendation in plain language", async () => {
    mockFetch(() => respond(200, noMove));
    await openStreaming();
    expect(await screen.findByText("No move — hold your roster")).toBeInTheDocument();
    expect(screen.getByTestId("streaming-no-move")).toHaveTextContent(
      "No legal add/drop improves your projected starting lineup this week.",
    );
    expect(screen.queryByTestId("streaming-recommendation")).toBeNull();
  });

  it("says when the dynasty budget is what stops the move", async () => {
    mockFetch(() => respond(200, budgetBinds));
    await openStreaming();
    expect(await screen.findByTestId("streaming-no-move")).toHaveTextContent(
      "Your dynasty budget is what stops a move. A budget of 250 would allow: Add Tyrell Gaines · Drop Andre Whitfield",
    );
  });

  it("states a bounded solve with its proven gap", async () => {
    mockFetch(() => respond(200, bounded));
    await openStreaming();
    expect(
      await screen.findAllByText(
        `Bounded — best found, proven within ${bounded.solver.boundGap.toFixed(1)} points`,
        { exact: false },
      ),
    ).not.toHaveLength(0);
    // Each capacity row carries its own search status; bounded rows are not "proven".
    const curve = screen.getByTestId("streaming-capacity-curve");
    expect(within(curve).getAllByText("Bounded — not proven").length).toBe(
      bounded.capacityCurve.filter((r) => r.status === "bounded" && r.searched !== false).length,
    );
    // Rows the work budget never reached are lower bounds, labelled apart.
    expect(within(curve).getAllByText("Not searched (lower bound)").length).toBe(
      bounded.capacityCurve.filter((r) => r.searched === false).length,
    );
    expect(screen.getByText(/were not\s+searched \(the request's work budget ran out\)/)).toBeInTheDocument();
  });

  it("sends changed controls to the backend (it decides, the page does not)", async () => {
    mockFetch((body) => respond(200, body.dynastyBudget >= 300 ? recommend : budgetLimited));
    await openStreaming();
    await screen.findByTestId("streaming-recommendation");
    fireEvent.change(screen.getByLabelText("Streaming capacity"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("radio", { name: "LB" }));
    fireEvent.click(screen.getByRole("radio", { name: "2 wk" }));
    fireEvent.change(screen.getByLabelText("Week"), { target: { value: "11" } });
    const budget = screen.getByLabelText("Dynasty loss budget");
    fireEvent.change(budget, { target: { value: "300" } });
    fireEvent.blur(budget);
    await waitFor(() =>
      expect(streamingCalls().at(-1)).toEqual({
        leagueKey: "dynasty_main",
        teamOwnerId: "owner-me",
        week: 11,
        horizonWeeks: 2,
        position: "LB",
        capacity: 4,
        dynastyBudget: 300,
      }),
    );
    // Typing alone does not refetch: the budget commits on blur / Enter.
    const before = streamingCalls().length;
    fireEvent.change(budget, { target: { value: "350" } });
    expect(streamingCalls().length).toBe(before);
  });

  it.each([
    [503, { error: "projections_refused" }, /Weekly projections are unavailable/],
    [400, { error: "not_in_season" }, /not the NFL season/],
    [503, { error: "starter_slots_unknown" }, /starting lineup slots are unknown/],
    [400, { error: "bad_dynastyBudget" }, /dynasty budget must be a number/],
    [503, { error: "idp_streaming_unavailable", reason: "league_settings_unreadable" }, /league's settings could not be read/],
  ])("states the %s %o failure", async (status, body, text) => {
    mockFetch(() => respond(status, body));
    await openStreaming();
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByTestId("streaming-recommendation")).toBeNull();
  });
});

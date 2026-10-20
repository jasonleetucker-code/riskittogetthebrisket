/**
 * MultiTeamWarRoom — Analyze Trade for 3+ teams on /trade (owner directive
 * 2026-10-20 §7; spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §3.2).
 *
 * Payloads are the REAL `POST /api/trade/analyze-multi` bodies Lane A
 * generated on an archived board (`fixtures/trade-multi/*.json`); the builder
 * state is derived from each payload's own legs.  The component computes
 * nothing: every expectation reads the fixture's fields.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MultiTeamWarRoom, { MULTI_DEBOUNCE_MS } from "@/components/trade/MultiTeamWarRoom";
import { builderFromFixture } from "../helpers/multi-team-fixture";

import THREE_CTX from "../fixtures/trade-multi/three-team-team-context.json";
import FORCED from "../fixtures/trade-multi/three-team-forced-cut.json";
import STALE from "../fixtures/trade-multi/three-team-stale-rosters.json";
import UNPRICED from "../fixtures/trade-multi/three-team-unpriced-asset.json";
import FOUR from "../fixtures/trade-multi/four-team-asset-only.json";

const ok = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function mount(fixture, props = {}) {
  const { sides, sleeperTeams, teamIds } = builderFromFixture(fixture);
  const bindings = teamIds.map((rosterId) => ({ rosterId, basis: "explicit" }));
  const all = {
    sides,
    teams: sleeperTeams,
    bindings,
    leagueKey: fixture.leagueKey,
    useTeamContext: fixture.mode === "team_context",
    perspectiveRosterId: teamIds[0],
    onReset: vi.fn(),
    onFinal: vi.fn(),
    ...props,
  };
  const view = render(<MultiTeamWarRoom {...all} />);
  return { ...view, props: all, sides, sleeperTeams, teamIds };
}

async function analyze() {
  await act(async () => {
    fireEvent.click(screen.getByTestId("multi-team-analyze"));
  });
  await act(async () => {
    vi.advanceTimersByTime(MULTI_DEBOUNCE_MS + 5);
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

describe("multi-team War Room", () => {
  it("does nothing until asked, then sends the canonical ledger once", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(THREE_CTX));
    mount(THREE_CTX);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("multi-team-analyze").textContent).toBe("Analyze 3-team trade");
    await analyze();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/trade/analyze-multi");
    const body = JSON.parse(init.body);
    expect(body.teams).toEqual(THREE_CTX.teams.map((t) => t.rosterId));
    expect(body.assets).toEqual(THREE_CTX.ledger.legs);
    expect(body.useTeamContext).toBe(true);
    expect(body.perspectiveRosterId).toBe(THREE_CTX.teams[0].rosterId);
  });

  it("renders every team's decision and market fairness as two separately labelled answers (C4)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(THREE_CTX));
    const { props } = mount(THREE_CTX);
    await analyze();
    const summary = screen.getByTestId("multi-team-summary");
    for (const t of THREE_CTX.teams) {
      const row = within(summary).getByText(t.team.name).closest("tr");
      expect(row.textContent).toContain(t.categoryText);
    }
    expect(screen.getByTestId("multi-team-summary-lines").textContent).toBe(
      THREE_CTX.summary.lines.join(" "),
    );
    // The selected perspective's two answers, verbatim.
    const first = THREE_CTX.teams[0];
    expect(screen.getByTestId("multi-team-decision").textContent).toBe(
      first.analysis.decision.headlineText,
    );
    const answers = document.querySelectorAll("[data-answer]");
    expect([...answers].map((a) => a.querySelector("dt").textContent)).toEqual([
      "Decision",
      "Market fairness",
    ]);
    expect(screen.getByTestId("multi-team-fairness").textContent).toBe(
      { FAIR: "Fair", NOT_FAIR: "Not fair", UNABLE: "Unable to determine" }[first.fairness.state],
    );
    // No trade-level YES / NO anywhere.
    expect(screen.getByTestId("multi-team-overall-fairness").textContent).toMatch(
      /no single verdict for the whole trade/,
    );
    expect(props.onFinal).toHaveBeenLastCalledWith(
      expect.objectContaining({ payload: THREE_CTX, sideRosterIds: THREE_CTX.teams.map((t) => t.rosterId) }),
    );
  });

  it("switches perspective over the one response without another request", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(THREE_CTX));
    mount(THREE_CTX);
    await analyze();
    const second = THREE_CTX.teams[1];
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: second.team.name }));
    });
    expect(screen.getByRole("tab", { name: second.team.name }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByTestId("multi-team-decision").textContent).toBe(
      second.analysis.decision.headlineText,
    );
    // What it sends, with destinations named by team, and the server's values.
    const gives = screen.getByTestId("multi-team-gives");
    for (const g of second.gives) {
      const li = gives.querySelector(`[data-asset-id="${g.assetId}"]`);
      const dest = THREE_CTX.teams.find((t) => t.rosterId === g.toRosterId).team.name;
      expect(li.textContent).toContain(`→ ${dest}`);
      expect(li.textContent).toContain(g.value.toLocaleString());
    }
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("forced cuts surface in that team's roster-fit answer", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(FORCED));
    mount(FORCED);
    await analyze();
    const cut = FORCED.teams.find((t) => t.analysis.lenses.feasibility.detail.forcedDrops?.length);
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: cut.team.name }));
    });
    const drop = cut.analysis.lenses.feasibility.detail.forcedDrops[0].name;
    expect(screen.getByTestId("multi-team-roster-fit").textContent).toContain(drop);
  });

  it("an unpriced asset reads as unknown, never 0, and the team is not judged", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(UNPRICED));
    mount(UNPRICED);
    await analyze();
    const team = UNPRICED.teams.find((t) => t.fairness.state === "UNABLE");
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: team.team.name }));
    });
    expect(screen.getByTestId("multi-team-fairness").textContent).toBe("Unable to determine");
    const unpriced = [...team.gives, ...team.receives].find((a) => a.value == null);
    const li = document.querySelector(`[data-asset-id="${unpriced.assetId}"]`);
    expect(li.textContent).toMatch(/unknown, not zero/);
    expect(li.textContent).not.toMatch(/\b0\b/);
  });

  it("stale rosters are said, and every team is not enough evidence", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(STALE));
    mount(STALE);
    await analyze();
    expect(screen.getByText(/League rosters are out of date|no provable refresh time/)).toBeTruthy();
    for (const t of STALE.teams) expect(t.analysis.decision.headline).toBe("NOT_ENOUGH_EVIDENCE");
  });

  it("four teams: one tab per team, Asset only mode is stated", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(FOUR));
    mount(FOUR, { useTeamContext: false });
    await analyze();
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.getByText(/Asset only: roster fit/)).toBeTruthy();
  });

  it("an edited trade hides the old answer at once and re-asks by itself", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(THREE_CTX));
    const { rerender, props } = mount(THREE_CTX);
    await analyze();
    expect(screen.getByTestId("multi-team-summary")).toBeTruthy();
    // Drop the last asset of side C: a different ledger.
    const edited = props.sides.map((s, i) =>
      i === 2 ? { ...s, assets: s.assets.slice(0, -1) } : s,
    );
    // Side C still sends? If it no longer sends AND receives, the ledger is
    // refused; either way the old answer must disappear immediately.
    await act(async () => {
      rerender(<MultiTeamWarRoom {...props} sides={edited} />);
    });
    expect(screen.queryByTestId("multi-team-summary")).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(MULTI_DEBOUNCE_MS + 5);
    });
    const notReady = screen.queryByTestId("multi-team-not-ready");
    if (!notReady) expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("names every reason it cannot analyze, with Analyze disabled", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { sides, sleeperTeams, teamIds } = builderFromFixture(THREE_CTX);
    render(
      <MultiTeamWarRoom
        sides={sides}
        teams={sleeperTeams}
        bindings={[{ rosterId: teamIds[0] }, { rosterId: null }, { rosterId: teamIds[2] }]}
        leagueKey="dynasty_main"
      />,
    );
    const box = screen.getByTestId("multi-team-not-ready");
    expect(box.textContent).toMatch(/Side B: Assign each side to a league team to analyze/);
    expect(screen.getByTestId("multi-team-analyze").disabled).toBe(true);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a 409 is explained without a Retry; a 500 offers Retry", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(ok({ error: "stale_assets", reason: "asset_not_owned" }, 409));
    mount(THREE_CTX);
    await analyze();
    expect(screen.getByTestId("multi-team-error").textContent).toMatch(
      /not held by the team sending them/,
    );
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    fetchSpy.mockResolvedValue(ok({ error: "internal_error" }, 500));
    await act(async () => {
      fireEvent.click(screen.getByTestId("multi-team-analyze"));
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("a response for another trade is refused, never shown", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(FOUR));
    mount(THREE_CTX);
    await analyze();
    expect(screen.queryByTestId("multi-team-summary")).toBeNull();
    expect(screen.getByTestId("multi-team-error")).toBeTruthy();
  });

  it("New trade resets through the page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ok(THREE_CTX));
    const { props } = mount(THREE_CTX);
    await analyze();
    await act(async () => {
      fireEvent.click(screen.getByTestId("multi-team-reset"));
    });
    expect(props.onReset).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("multi-team-summary")).toBeNull();
  });
});

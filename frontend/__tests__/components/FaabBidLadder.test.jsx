/**
 * FAAB bid desk — the two-group split and the full ladder.
 *
 * The engine redesign (``src/trade/faab_engine.py``) turns on ONE
 * separation the old panel did not make at all:
 *
 *   objective ceiling — what the player is WORTH.  A function of the
 *     player and the league FORMAT, expressed against the ORIGINAL
 *     budget.  Identical for every team; unmoved by what you spent.
 *   recommended bid   — what THIS team should pay.  Dominated by the
 *     price the claim is expected to clear at, so it is almost always
 *     far below the ceiling.
 *
 * These tests exist because the failure mode is silent: render both in
 * one undifferentiated strip of pills and a user reads the ceiling as a
 * bid, which is exactly the mistake the engine was rewritten to stop.
 * So the assertions are about SEPARATION and LABELLING, not just about
 * the numbers appearing somewhere on screen.
 *
 * They also pin the backward-compatibility contract: the old
 * conservative/standard/aggressive/max keys still resolve, and a
 * backend that stamps no ``objective`` hides that group entirely rather
 * than rendering a row of em dashes.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";

import FaabRecommendation from "@/components/waivers/FaabRecommendation";

function mockFetch(json) {
  const fn = vi.fn().mockResolvedValue({ ok: true, json: async () => json });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** A full modern payload — engine keys AND the legacy ones it still stamps. */
function enginePayload(overrides = {}) {
  return {
    objective: {
      dollars: 74,
      pctOfOriginalBudget: 74.0,
      originalBudget: 100,
      surplusOverReplacement: 1560.4,
    },
    bids: {
      recommended: 36,
      conservative: 24,
      aggressive: 48,
      maxRational: 62,
      clearing: 31,
    },
    pctOfOriginalBudget: 36.0,
    pctOfRemaining: 47.4,
    winProbability: 0.61,
    anchors: { vAllIn: 3901, vReplacement: 1120, band: 0.12, starterSlots: 240 },
    teamCeilingDollars: 62,
    optionValueFactor: 1.08,
    riskPosture: "balanced",
    // Legacy keys — still stamped, still correct.
    conservative: 24,
    standard: 36,
    aggressive: 48,
    max: 62,
    confidence: "high",
    explanation: "Bid $36 — worth up to $74 of the original $100 budget.",
    factors: [],
    warnings: [],
    ...overrides,
  };
}

function renderDesk(props = {}) {
  return render(
    <FaabRecommendation
      addPlayer={{ name: "Jaylen Waddle" }}
      dropPlayer={null}
      leagueKey="dynasty_main"
      ownerId="me"
      selectedTeam={{ ownerId: "me", name: "Me" }}
      leagueFaab={null}
      {...props}
    />,
  );
}

const worthGroup = () =>
  screen.getByRole("region", { name: /What the player is worth/i });
const bidGroup = () => screen.getByRole("region", { name: /What you should bid/i });

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FAAB bid desk — worth and bid are separate groups", () => {
  it("puts the objective value in its own group, labelled against the ORIGINAL budget", async () => {
    mockFetch(enginePayload());
    renderDesk();

    const worth = await screen.findByRole("region", {
      name: /What the player is worth/i,
    });
    expect(within(worth).getByText("$74")).toBeInTheDocument();
    // The percentage must name the ORIGINAL budget — a share of the
    // remaining balance would make this number team-dependent, which is
    // the whole thing it is not.
    expect(
      within(worth).getByText(/74\.0% of the original \$100 budget/i),
    ).toBeInTheDocument();
    // Budget-independence has to be stated, not implied.
    expect(within(worth).getByText(/Budget-independent/i)).toBeInTheDocument();
    // …and the recommended bid must NOT be in this group.
    expect(within(worth).queryByText("$36")).toBeNull();
  });

  it("surfaces surplus over replacement as board value, not dollars", async () => {
    mockFetch(enginePayload());
    renderDesk();
    const worth = await screen.findByRole("region", {
      name: /What the player is worth/i,
    });
    const tile = within(worth).getByText("Surplus over replacement").closest(".ds-stat");
    // 1560.4 board points — rounded, and deliberately NOT dollar-signed.
    expect(within(tile).getByText("1,560")).toBeInTheDocument();
  });

  it("renders the full ladder in the bid group, with the win chance on the recommendation", async () => {
    mockFetch(enginePayload());
    renderDesk();

    const bid = await screen.findByRole("region", { name: /What you should bid/i });
    const tileFor = (label) => within(bid).getByText(label).closest(".ds-stat");

    expect(within(tileFor("Recommended")).getByText("$36")).toBeInTheDocument();
    expect(
      within(tileFor("Recommended")).getByText(/61% chance of winning/i),
    ).toBeInTheDocument();
    expect(within(tileFor("Conservative")).getByText("$24")).toBeInTheDocument();
    expect(within(tileFor("Aggressive")).getByText("$48")).toBeInTheDocument();
    expect(within(tileFor("Max rational")).getByText("$62")).toBeInTheDocument();
    expect(within(tileFor("Est. market-clearing")).getByText("$31")).toBeInTheDocument();
  });

  it("qualifies the bid with both budget shares, confidence and posture", async () => {
    mockFetch(enginePayload());
    renderDesk();

    const bid = await screen.findByRole("region", { name: /What you should bid/i });
    expect(within(bid).getByText("36.0%")).toBeInTheDocument();
    expect(within(bid).getByText("47.4%")).toBeInTheDocument();
    expect(within(bid).getByText(/Of remaining budget/i)).toBeInTheDocument();
    expect(within(bid).getByText("High confidence")).toBeInTheDocument();
    // "Balanced posture", not a bare "Balanced": the ladder already has
    // rungs named Conservative and Aggressive, so a bare posture word
    // would be indistinguishable from a bid tier.
    expect(within(bid).getByText("Balanced posture")).toBeInTheDocument();
    expect(
      within(bid).getByText(/worth up to \$74 of the original \$100 budget/i),
    ).toBeInTheDocument();
  });

  it("says n/a — never 0% — when the backend reports no usable remaining balance", async () => {
    // ``pctOfRemaining: null`` is the backend saying "your balance is
    // zero or unknown".  Rendering that as 0% would read as "this bid is
    // free", which is the opposite of what it means.
    mockFetch(enginePayload({ pctOfRemaining: null }));
    renderDesk();
    const bid = await screen.findByRole("region", { name: /What you should bid/i });
    expect(within(bid).getByText("n/a")).toBeInTheDocument();
    expect(within(bid).queryByText("0.0%")).toBeNull();
  });
});

describe("FAAB bid desk — backward compatibility", () => {
  it("renders the ladder from legacy keys and hides the objective group entirely", async () => {
    // An older backend (or a payload predating the engine) stamps only
    // conservative/standard/aggressive/max.  The panel must degrade to
    // the v1 read, not to a grid of em dashes under a heading claiming
    // to know what the player is worth.
    mockFetch({
      conservative: 12,
      standard: 20,
      aggressive: 30,
      max: 100,
      confidence: "medium",
      explanation: "Scarce starter-quality WR on a thin bench.",
      factors: [],
      warnings: [],
    });
    renderDesk();

    const bid = await screen.findByRole("region", { name: /What you should bid/i });
    expect(
      screen.queryByRole("region", { name: /What the player is worth/i }),
    ).toBeNull();

    const tileFor = (label) => within(bid).getByText(label).closest(".ds-stat");
    expect(within(tileFor("Recommended")).getByText("$20")).toBeInTheDocument();
    expect(within(tileFor("Max rational")).getByText("$100")).toBeInTheDocument();
    // No clearing price was stamped — a placeholder, never a guess.
    expect(within(tileFor("Est. market-clearing")).getByText("—")).toBeInTheDocument();
  });
});

describe("FAAB bid desk — risk posture reaches the backend", () => {
  it("sends the selected posture in the request body", async () => {
    const fetchMock = mockFetch(enginePayload({ riskPosture: "aggressive" }));
    renderDesk({ riskPosture: "aggressive" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/waiver/faab-recommend");
    expect(JSON.parse(init.body).riskPosture).toBe("aggressive");

    // The panel reports the posture the BACKEND said it used, so an
    // ignored posture is visible rather than silent.
    //
    // waitFor, not a bare assertion: the wait above only proves the
    // fetch was CALLED.  Rendering the result needs the promise to
    // resolve and React to flush, which is fast enough locally to hide
    // the gap and slow enough on a loaded CI runner to fail on the
    // loading skeleton.
    await waitFor(() =>
      expect(within(bidGroup()).getByText("Aggressive posture")).toBeInTheDocument(),
    );
  });

  it("normalizes an unknown posture to balanced instead of shipping it", async () => {
    // The engine treats an unrecognised string as "balanced", so sending
    // one would mean the UI claimed a posture the backend never applied.
    const fetchMock = mockFetch(enginePayload());
    renderDesk({ riskPosture: "reckless" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).riskPosture).toBe("balanced");
  });

  it("defaults to balanced when no posture is passed", async () => {
    const fetchMock = mockFetch(enginePayload());
    renderDesk();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).riskPosture).toBe("balanced");
  });

  it("refetches when the posture changes", async () => {
    const fetchMock = mockFetch(enginePayload());
    const { rerender } = renderDesk({ riskPosture: "balanced" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rerender(
      <FaabRecommendation
        addPlayer={{ name: "Jaylen Waddle" }}
        dropPlayer={null}
        leagueKey="dynasty_main"
        ownerId="me"
        selectedTeam={{ ownerId: "me", name: "Me" }}
        leagueFaab={null}
        riskPosture="conservative"
      />,
    );
    // A stale ladder under a freshly-chosen posture looks exactly like
    // the control being broken.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).riskPosture).toBe(
      "conservative",
    );
  });
});

describe("FAAB bid desk — the two clearing prices are distinct reads", () => {
  it("does not collide the engine's clearing estimate with the rival-model one", async () => {
    // ``bids.clearing`` comes from the engine's rival-bid distribution;
    // ``contention.clearing`` comes from the per-opponent estimator.
    // They are different models and must stay separately labelled.
    mockFetch(
      enginePayload({
        contention: {
          clearing: 44,
          topRival: 41,
          perOpponent: [],
          estimateOnly: true,
          notes: [],
          skipped: false,
        },
      }),
    );
    renderDesk();

    const bid = await screen.findByRole("region", { name: /What you should bid/i });
    const engineTile = within(bid)
      .getByText("Est. market-clearing")
      .closest(".ds-stat");
    expect(within(engineTile).getByText("$31")).toBeInTheDocument();

    const rivalTile = screen.getByText("Clearing price").closest(".ds-stat");
    expect(within(rivalTile).getByText("$44")).toBeInTheDocument();
    expect(worthGroup()).toBeInTheDocument();
  });
});

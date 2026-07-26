/**
 * FAAB v2 rival-contention UI (R4 review, P2-4).
 *
 * The contention block — clearing price, projected top rival, and the
 * per-rival bid table — is a NEW feature that shipped in R4 under a
 * "preserved verbatim" description with zero tests.  These tests pin
 * it against the real wire format:
 *
 *   server.py::post_waiver_faab_recommend  ->  rec["contention"] =
 *     {clearing, topRival, perOpponent, estimateOnly, notes, skipped}
 *   src/trade/faab_contention.py           ->  perOpponent rows carry
 *     {ownerId, teamName, expBid, faabRemaining, needLevel,
 *      aggression, lowSample, intelLevel, capped, balanceUnknown}
 *
 * The important behaviours are the HONESTY ones: a skipped contention
 * must say so rather than render an empty desk, and a rival whose FAAB
 * balance we cannot verify must be visibly flagged — the backend
 * already excludes them from clearing/topRival so the UI must not
 * imply they were counted.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import FaabRecommendation from "@/components/waivers/FaabRecommendation";

function rival(overrides = {}) {
  return {
    ownerId: overrides.ownerId || "o1",
    teamName: overrides.teamName || "Rival One",
    expBid: overrides.expBid ?? 24,
    faabRemaining: overrides.faabRemaining ?? 80,
    needLevel: overrides.needLevel || "high",
    aggression: overrides.aggression ?? 1.25,
    lowSample: overrides.lowSample ?? false,
    intelLevel: overrides.intelLevel || "none",
    capped: overrides.capped ?? false,
    balanceUnknown: overrides.balanceUnknown ?? false,
    ...overrides,
  };
}

function payload(contention) {
  return {
    conservative: 12,
    standard: 20,
    aggressive: 30,
    max: 100,
    confidence: "medium",
    explanation: "Scarce starter-quality WR on a thin bench.",
    factors: [],
    warnings: [],
    contention,
  };
}

function mockFetchOnce(json) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => json }),
  );
}

function renderDesk() {
  return render(
    <FaabRecommendation
      addPlayer={{ name: "Jaylen Waddle" }}
      dropPlayer={null}
      leagueKey="dynasty_main"
      ownerId="me"
      selectedTeam={{ ownerId: "me", name: "Me" }}
      leagueFaab={null}
    />,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FAAB contention — headline reads", () => {
  it("surfaces clearing price and projected top rival from the wire payload", async () => {
    mockFetchOnce(
      payload({
        clearing: 25,
        topRival: 24,
        perOpponent: [rival()],
        estimateOnly: true,
        notes: [],
        skipped: false,
      }),
    );
    renderDesk();

    // Scope to the tiles: $24 also appears as the rival's row value, so
    // a bare getByText would be ambiguous (and would pass for the wrong
    // reason if the tile ever stopped rendering).
    const clearingTile = (await screen.findByText("Clearing price")).closest(
      ".ds-stat",
    );
    expect(within(clearingTile).getByText("$25")).toBeInTheDocument();

    const topRivalTile = screen.getByText("Projected top rival").closest(".ds-stat");
    expect(within(topRivalTile).getByText("$24")).toBeInTheDocument();
    // the count line reflects how many rivals were actually modeled
    expect(within(topRivalTile).getByText("of 1 rivals")).toBeInTheDocument();
  });

  it("renders one table row per modeled rival, highest estimated bid first", async () => {
    mockFetchOnce(
      payload({
        clearing: 41,
        topRival: 40,
        perOpponent: [
          rival({ ownerId: "o1", teamName: "Low Bidder", expBid: 12 }),
          rival({ ownerId: "o2", teamName: "Top Bidder", expBid: 40 }),
          rival({ ownerId: "o3", teamName: "Mid Bidder", expBid: 25 }),
        ],
        estimateOnly: true,
        notes: [],
        skipped: false,
      }),
    );
    renderDesk();

    const table = await screen.findByRole("table", {
      name: /Estimated rival bids/i,
    });
    const names = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(names[0]).toMatch(/Top Bidder/);
    expect(names[1]).toMatch(/Mid Bidder/);
    expect(names[2]).toMatch(/Low Bidder/);
  });
});

describe("FAAB contention — honesty about what was counted", () => {
  it("explains itself instead of rendering an empty desk when contention is skipped", async () => {
    mockFetchOnce(
      payload({
        skipped: true,
        notes: [
          "teamOwnerId not provided — rival contention skipped (we never guess which team is yours).",
        ],
      }),
    );
    renderDesk();

    expect(
      await screen.findByText(/Rival contention not modeled/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/we never guess which team is yours/i)).toBeInTheDocument();
    // no rival table is implied when nothing was modeled
    expect(screen.queryByRole("table", { name: /Estimated rival bids/i })).toBeNull();
  });

  it("flags a rival whose FAAB balance could not be verified", async () => {
    // The backend EXCLUDES these from clearing/topRival, so the UI must
    // not let them read as counted.
    mockFetchOnce(
      payload({
        clearing: 25,
        topRival: 24,
        perOpponent: [
          rival({ ownerId: "o1", teamName: "Known Team" }),
          rival({
            ownerId: "o2",
            teamName: "Opaque Team",
            faabRemaining: null,
            balanceUnknown: true,
          }),
        ],
        estimateOnly: true,
        notes: [],
        skipped: false,
      }),
    );
    renderDesk();

    const table = await screen.findByRole("table", {
      name: /Estimated rival bids/i,
    });
    const opaqueRow = within(table)
      .getAllByRole("row")
      .find((r) => r.textContent.includes("Opaque Team"));
    expect(within(opaqueRow).getByText("no balance")).toBeInTheDocument();
    // …and an unknown balance renders as an em dash, never as $0
    expect(opaqueRow.textContent).toContain("—");
    expect(opaqueRow.textContent).not.toContain("$0");
  });

  it("flags thin bid history and available intel per rival", async () => {
    mockFetchOnce(
      payload({
        clearing: 20,
        topRival: 19,
        perOpponent: [
          rival({ ownerId: "o1", teamName: "Thin Team", lowSample: true }),
          rival({ ownerId: "o2", teamName: "Intel Team", intelLevel: "high" }),
        ],
        estimateOnly: true,
        notes: [],
        skipped: false,
      }),
    );
    renderDesk();

    const table = await screen.findByRole("table", {
      name: /Estimated rival bids/i,
    });
    const rows = within(table).getAllByRole("row");
    const thin = rows.find((r) => r.textContent.includes("Thin Team"));
    const intel = rows.find((r) => r.textContent.includes("Intel Team"));
    expect(within(thin).getByText("thin history")).toBeInTheDocument();
    expect(within(intel).getByText("intel")).toBeInTheDocument();
    // "none" intel must NOT produce a badge
    expect(within(thin).queryByText("intel")).toBeNull();
  });

  it("renders the recommender's caveat notes verbatim", async () => {
    mockFetchOnce(
      payload({
        clearing: 25,
        topRival: 24,
        perOpponent: [rival()],
        estimateOnly: true,
        notes: [
          "Rival bids are estimates from winning-bid history only — losing bids are invisible.",
          "Two rivals had no verifiable balance and were excluded.",
        ],
        skipped: false,
      }),
    );
    renderDesk();

    expect(
      await screen.findByText(/losing bids are invisible/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no verifiable balance and were excluded/i),
    ).toBeInTheDocument();
  });

  it("omits the contention block entirely when the payload has no contention key", async () => {
    mockFetchOnce(payload(undefined));
    renderDesk();
    // the bid desk still renders…
    expect(await screen.findByText("Recommended")).toBeInTheDocument();
    // …but nothing claims a rival read
    expect(screen.queryByText("Clearing price")).toBeNull();
    expect(screen.queryByText(/Rival contention not modeled/i)).toBeNull();
  });
});

describe("FAAB contention — rival table is sortable and accessible", () => {
  it("exposes sortable rival columns as buttons with aria-sort", async () => {
    const user = userEvent.setup();
    mockFetchOnce(
      payload({
        clearing: 41,
        topRival: 40,
        perOpponent: [
          rival({ ownerId: "o1", teamName: "A Team", expBid: 12, faabRemaining: 90 }),
          rival({ ownerId: "o2", teamName: "B Team", expBid: 40, faabRemaining: 10 }),
        ],
        estimateOnly: true,
        notes: [],
        skipped: false,
      }),
    );
    renderDesk();

    const table = await screen.findByRole("table", {
      name: /Estimated rival bids/i,
    });
    // default sort: estimated bid, descending
    expect(
      within(table).getByRole("columnheader", { name: /Est\. bid/ }),
    ).toHaveAttribute("aria-sort", "descending");

    await user.click(within(table).getByRole("button", { name: /Their FAAB/ }));
    expect(
      within(table).getByRole("columnheader", { name: /Their FAAB/ }),
    ).toHaveAttribute("aria-sort", "descending");
  });
});

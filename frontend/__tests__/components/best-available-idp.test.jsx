/**
 * BestAvailableIdps — the "Best available IDPs" waivers card.
 *
 * Display-only component: every score arrives pre-computed from
 * ``POST /api/waiver/best-available-idp`` (src/trade/waiver_idp_best_available.py).
 * ``useBestAvailableIdp`` is mocked directly here (it's a thin fetch
 * wrapper, already mirrored on the well-tested ``useWaiverAnalysis``
 * bid-fetch pattern) so these tests focus on rendering: degraded
 * states, tier labeling, truthful counts, and the mobile-safe table
 * structure DataTable already guarantees.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const mockUseBestAvailableIdp = vi.fn();
vi.mock("@/components/useBestAvailableIdp", () => ({
  useBestAvailableIdp: (...args) => mockUseBestAvailableIdp(...args),
}));

import BestAvailableIdps from "@/components/waivers/BestAvailableIdps";

function candidate(overrides = {}) {
  return {
    name: "Test Player",
    team: "XX",
    position: "LB",
    tier: "A",
    combinedScore: 75.0,
    sourcesUsed: 2,
    idpTradeCalc: { rank: 5, rawValue: 8000, score: 80.0 },
    idpShowCombined: { rank: 6, rawRank: 6, score: 70.0 },
    ...overrides,
  };
}

describe("BestAvailableIdps — visibility", () => {
  it("renders nothing when the league doesn't have IDP enabled", () => {
    mockUseBestAvailableIdp.mockReturnValue({ payload: null, loading: false });
    const { container } = render(
      <BestAvailableIdps leagueKey="main" idpEnabled={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("BestAvailableIdps — Tier B labeling", () => {
  it("marks a one-source candidate '1 of 2 sources'", () => {
    mockUseBestAvailableIdp.mockReturnValue({
      payload: {
        ownershipResolved: true,
        candidates: [candidate({ tier: "B", sourcesUsed: 1, idpShowCombined: { rank: null, rawRank: null, score: null } })],
        availableCount: 1,
        sources: { idpTradeCalc: { populationSize: 10 }, idpShowCombined: { populationSize: 10 } },
        degraded: { ownershipUnresolved: false, missingSources: [] },
        sourceFreshness: {},
      },
      loading: false,
    });
    render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    expect(screen.getByText("1 of 2 sources")).toBeInTheDocument();
  });

  it("does not label a two-source candidate", () => {
    mockUseBestAvailableIdp.mockReturnValue({
      payload: {
        ownershipResolved: true,
        candidates: [candidate({ tier: "A" })],
        availableCount: 1,
        sources: { idpTradeCalc: { populationSize: 10 }, idpShowCombined: { populationSize: 10 } },
        degraded: { ownershipUnresolved: false, missingSources: [] },
        sourceFreshness: {},
      },
      loading: false,
    });
    render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    expect(screen.queryByText("1 of 2 sources")).not.toBeInTheDocument();
  });
});

describe("BestAvailableIdps — degraded states", () => {
  it("shows 'Availability unavailable' when ownership can't be resolved", () => {
    mockUseBestAvailableIdp.mockReturnValue({
      payload: {
        ownershipResolved: false,
        candidates: [],
        availableCount: 0,
        sources: { idpTradeCalc: { populationSize: 0 }, idpShowCombined: { populationSize: 0 } },
        degraded: { ownershipUnresolved: true, missingSources: [] },
        sourceFreshness: {},
      },
      loading: false,
    });
    const { container } = render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    expect(container.textContent).toContain("Availability unavailable");
    // No fabricated table when ownership is unresolved.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("names the missing source rather than silently presenting a one-source combined score", () => {
    mockUseBestAvailableIdp.mockReturnValue({
      payload: {
        ownershipResolved: true,
        candidates: [candidate({ tier: "B" })],
        availableCount: 1,
        sources: { idpTradeCalc: { populationSize: 10 }, idpShowCombined: { populationSize: 0 } },
        degraded: { ownershipUnresolved: false, missingSources: ["idpShowCombined"] },
        sourceFreshness: {},
      },
      loading: false,
    });
    const { container } = render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    expect(screen.getByText("A source is missing")).toBeInTheDocument();
    expect(container.textContent).toContain("The IDP Show data is currently unavailable");
  });

  it("states the true count when fewer than 20 candidates qualify, without padding rows", () => {
    mockUseBestAvailableIdp.mockReturnValue({
      payload: {
        ownershipResolved: true,
        candidates: [candidate({ name: "Only One" })],
        availableCount: 1,
        sources: { idpTradeCalc: { populationSize: 1 }, idpShowCombined: { populationSize: 1 } },
        degraded: { ownershipUnresolved: false, missingSources: [] },
        sourceFreshness: {},
      },
      loading: false,
    });
    render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    expect(screen.getByText(/Showing all 1 available IDP free agent/)).toBeInTheDocument();
    expect(screen.getAllByText("Only One")).toHaveLength(1);
  });

  it("renders a loading state before the payload arrives", () => {
    mockUseBestAvailableIdp.mockReturnValue({ payload: null, loading: true });
    const { container } = render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    // A skeleton, not an empty state and not a crash.
    expect(container.querySelector("[aria-hidden='true']")).toBeTruthy();
    expect(screen.queryByText("Availability unavailable")).not.toBeInTheDocument();
  });

  it("shows an unavailable state when the fetch failed outright (no payload, not loading)", () => {
    mockUseBestAvailableIdp.mockReturnValue({ payload: null, loading: false });
    const { container } = render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    expect(container.textContent).toContain("Service unavailable");
    expect(container.textContent).toContain(
      "Couldn't reach the IDP Trade Calculator / The IDP Show comparison right now.",
    );
  });
});

describe("BestAvailableIdps — mobile-safe table structure", () => {
  it("wraps the table in DataTable's built-in horizontal-scroll container, never a bare table", () => {
    mockUseBestAvailableIdp.mockReturnValue({
      payload: {
        ownershipResolved: true,
        candidates: [candidate()],
        availableCount: 1,
        sources: { idpTradeCalc: { populationSize: 10 }, idpShowCombined: { populationSize: 10 } },
        degraded: { ownershipUnresolved: false, missingSources: [] },
        sourceFreshness: {},
      },
      loading: false,
    });
    const { container } = render(<BestAvailableIdps leagueKey="main" idpEnabled />);
    // DataTable's ``.ds-table-wrap`` is the horizontal-scroll boundary —
    // its presence is what keeps a wide row set from forcing the PAGE
    // to scroll horizontally at narrow widths (jsdom does not compute
    // real layout, so this is a structural guard; true pixel-level
    // overflow at ~390px is confirmed manually per the plan's
    // verification checklist).
    expect(container.querySelector(".ds-table-wrap")).toBeTruthy();
  });
});

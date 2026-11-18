// /waivers page — two verified defects from the 2026-11-16 sweep.
//
// 1. MISSING IS NEVER ZERO: when the canonical cut ladder could not be
//    read, every drop-dependent list is empty BECAUSE the ladder is
//    missing (lib/waiver-logic.js::computeWaiverAnalysis), yet the summary
//    tiles printed "0" addable / droppable players and "no upgrades vs
//    roster", and the Best-moves / Addable empty states blamed the user's
//    filters.  Those are measurements nobody made.  The tiles now read "—"
//    + "cut ladder unavailable" and the empty states name the ladder.
// 2. With a team selected and no bid index, every FAAB cell said "No bids"
//    with "Pick your team above" — false for a user who has picked one.
//
// useWaiverAnalysis is stubbed: this file is about what the PAGE renders
// for each analysis state, not the hook's fetches (those have their own
// tests).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

const mockAnalysis = vi.fn();

vi.mock("@/components/useWaiverAnalysis", () => ({
  useWaiverAnalysis: () => mockAnalysis(),
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ privateDataEnabled: true, rows: [], rawData: { sleeper: { teams: [] } } }),
}));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => ({ authenticated: true }) }));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: { key: "dynasty_main", idpEnabled: true } }),
}));
vi.mock("@/components/useTeam", () => ({
  // No ownerId: keeps the lazy Perfect Waivers panel (and its fetch) out.
  useTeam: () => ({ selectedTeam: { name: "Mine", players: [] }, loading: false }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, hydrated: true, update: vi.fn() }),
}));
vi.mock("@/components/waivers/ManualAddDrop", () => ({ default: () => null }));
vi.mock("@/components/waivers/BestAvailableIdps", () => ({ default: () => null }));
vi.mock("@/components/TeamSwitcher", () => ({ default: () => null }));
vi.mock("@/components/shell/RelatedLinks", () => ({ default: () => null }));

import WaiversPage from "@/app/waivers/page";

const EMPTY_SUMMARY = {
  bestAddable: null,
  bestGain: 0,
  addableCount: 0,
  droppableCount: 0,
  rookieAddCount: 0,
  rosterSize: 20,
  freeAgentPoolSize: 300,
};

function analysis(overrides = {}) {
  return {
    addable: [],
    droppable: [],
    bestMoves: [],
    bestUniqueUpgradeSet: [],
    summary: EMPTY_SUMMARY,
    dropState: { state: "ok", reason: "", reasonText: "", undroppableCount: 0 },
    ...overrides,
  };
}

function hookResult(a, extra = {}) {
  return {
    analysis: a,
    faabIndex: null,
    loading: false,
    error: null,
    leagueMismatch: false,
    hasTeam: true,
    teamCount: 12,
    selectedLeagueName: "Main",
    ...extra,
  };
}

const UNAVAILABLE = {
  state: "unavailable",
  reason: "error",
  reasonText: "roster intelligence could not be loaded",
  undroppableCount: null,
};

function tile(label) {
  const el = screen.getByText(label).closest(".ds-stat");
  return {
    value: el.querySelector(".ds-stat__value").textContent,
    meta: el.querySelector(".ds-stat__meta")?.textContent ?? null,
  };
}

beforeEach(() => mockAnalysis.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe("cut ladder unavailable — counts are unknown, not zero", () => {
  it("summary tiles read '—' + 'cut ladder unavailable', never 0 or 'no upgrades vs roster'", () => {
    mockAnalysis.mockReturnValue(hookResult(analysis({ dropState: UNAVAILABLE })));
    render(<WaiversPage />);

    expect(screen.getByText("Drop candidates unavailable")).toBeInTheDocument();
    for (const label of ["Best available", "Top net gain", "Addable players", "Droppable players"]) {
      expect(tile(label)).toEqual({ value: "—", meta: "cut ladder unavailable" });
    }
    expect(screen.queryByText("no upgrades vs roster")).toBeNull();
  });

  it("the empty states name the missing ladder, not the user's filters", () => {
    mockAnalysis.mockReturnValue(hookResult(analysis({ dropState: UNAVAILABLE })));
    render(<WaiversPage />);

    expect(screen.queryByText("No upgrades match your filters")).toBeNull();
    expect(screen.queryByText("No addable players")).toBeNull();
    expect(screen.getByText("No add/drop moves shown")).toBeInTheDocument();
    expect(screen.getByText("No addable players shown")).toBeInTheDocument();
    // Droppable already stated it; unchanged.
    expect(screen.getByText("No drop candidates shown")).toBeInTheDocument();
    expect(screen.getAllByText(/Your cut ladder could not be read/).length).toBeGreaterThanOrEqual(3);
  });

  it("with the ladder read, a genuine empty result keeps its measured copy (regression)", () => {
    mockAnalysis.mockReturnValue(hookResult(analysis()));
    render(<WaiversPage />);

    expect(screen.queryByText("Drop candidates unavailable")).toBeNull();
    expect(tile("Addable players")).toEqual({ value: "0", meta: "beat at least one of yours" });
    expect(tile("Best available").meta).toBe("no upgrades vs roster");
    expect(screen.getByText("No upgrades match your filters")).toBeInTheDocument();
    expect(screen.getByText("No addable players")).toBeInTheDocument();
  });

  it("the rookie tile is unknown too when rookies are in the mix", () => {
    mockAnalysis.mockReturnValue(hookResult(analysis({ dropState: UNAVAILABLE })));
    render(<WaiversPage />);
    // The rookie toggle lives on the page; its tile follows the same rule.
    fireEvent.click(screen.getByLabelText("Include rookies"));
    expect(tile("Rookies in mix")).toEqual({ value: "—", meta: "cut ladder unavailable" });
  });
});

describe("bid cells with a team selected never say 'Pick your team'", () => {
  const MOVE = {
    add: { name: "Emeka Egbuka", pos: "WR", team: "TB" },
    drop: { name: "Old Guy", pos: "WR" },
    netGain: 900,
    upgradeTier: "strong",
    isRookie: false,
  };

  it("no index + a selected team: 'Bids not loaded', no instruction to pick a team", () => {
    mockAnalysis.mockReturnValue(
      hookResult(
        analysis({
          bestMoves: [MOVE],
          summary: { ...EMPTY_SUMMARY, bestAddable: MOVE.add, bestGain: 900, addableCount: 1 },
        }),
      ),
    );
    render(<WaiversPage />);

    const table = screen.getByRole("table", { name: /Top single-transaction add\/drop upgrades/ });
    const figures = within(table).getAllByTestId("waiver-bid-figure");
    expect(figures.length).toBeGreaterThan(0);
    for (const f of figures) {
      expect(f).toHaveAttribute("data-state", "unavailable");
      expect(f.textContent).toBe("Bids not loaded");
      expect(f.getAttribute("title")).not.toMatch(/pick your team/i);
    }
  });
});

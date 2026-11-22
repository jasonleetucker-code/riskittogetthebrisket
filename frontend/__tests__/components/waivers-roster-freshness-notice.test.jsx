// /waivers — the roster-freshness notice (DYN10 B3).
//
// The waiver payloads now carry the server's ``rosterFreshness`` verdict
// (``src/api/roster_freshness.py``: current / stale / unknown).  A roster
// block restored from a last-good snapshot can list a free agent who has
// since been claimed, so the page warns — and ONLY when the verdict is not
// "current".  useWaiverAnalysis is stubbed: this is about what the page
// renders for each stamp.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
import { rosterFreshnessNotice } from "@/lib/waiver-logic";

const ANALYSIS = {
  addable: [],
  droppable: [],
  bestMoves: [],
  bestUniqueUpgradeSet: [],
  summary: {
    bestAddable: null,
    bestGain: 0,
    addableCount: 0,
    droppableCount: 0,
    rookieAddCount: 0,
    rosterSize: 20,
    freeAgentPoolSize: 300,
  },
  dropState: { state: "ok", reason: "", reasonText: "", undroppableCount: 0 },
};

function hookResult(rosterFreshness) {
  return {
    analysis: ANALYSIS,
    faabIndex: null,
    rosterFreshness,
    loading: false,
    error: null,
    leagueMismatch: false,
    hasTeam: true,
    teamCount: 12,
    selectedLeagueName: "Main",
  };
}

beforeEach(() => mockAnalysis.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe("roster freshness notice on /waivers", () => {
  it("warns when the rosters are a restored snapshot", () => {
    mockAnalysis.mockReturnValue(
      hookResult({ state: "stale", source: "last_good", ageHours: 9.4, delivery: "contract" }),
    );
    render(<WaiversPage />);
    expect(screen.getByText("Rosters may be out of date")).toBeInTheDocument();
    const notice = screen.getByTestId("waivers-roster-freshness");
    expect(notice).toHaveTextContent(/saved copy kept after a failed refresh/);
    expect(notice).toHaveTextContent(/9 h ago/);
    expect(notice).toHaveTextContent(/may already have been claimed/);
  });

  it("warns when freshness cannot be proven", () => {
    mockAnalysis.mockReturnValue(hookResult({ state: "unknown", ageHours: null }));
    render(<WaiversPage />);
    expect(screen.getByText("Roster freshness unknown")).toBeInTheDocument();
  });

  it("says nothing when the rosters are current", () => {
    mockAnalysis.mockReturnValue(
      hookResult({ state: "current", source: "live", ageHours: 0.1, delivery: "live_overlay" }),
    );
    render(<WaiversPage />);
    expect(screen.queryByTestId("waivers-roster-freshness")).toBeNull();
    expect(screen.queryByText("Rosters may be out of date")).toBeNull();
  });

  it("says nothing before any stamp has loaded", () => {
    mockAnalysis.mockReturnValue(hookResult(null));
    render(<WaiversPage />);
    expect(screen.queryByTestId("waivers-roster-freshness")).toBeNull();
  });
});

describe("rosterFreshnessNotice", () => {
  it("is null only for a current verdict or no stamp", () => {
    expect(rosterFreshnessNotice({ state: "current" })).toBeNull();
    expect(rosterFreshnessNotice(null)).toBeNull();
    expect(rosterFreshnessNotice(undefined)).toBeNull();
  });

  it("a stamp without a recognised state is unknown, never current", () => {
    expect(rosterFreshnessNotice({}).state).toBe("unknown");
    expect(rosterFreshnessNotice({ state: "fresh-ish" }).state).toBe("unknown");
  });

  it("an old live fetch is described as past the refresh window", () => {
    const notice = rosterFreshnessNotice({ state: "stale", source: "live", ageHours: 0.4 });
    expect(notice.text).toMatch(/older than the refresh window \(last fetched under an hour ago\)/);
  });
});

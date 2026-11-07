/**
 * UI-honesty disclosures for audit W27-F001 (IDP Edge) and W10-F003
 * (empty Next Best Targets).  Display only: no detector / threshold /
 * contract field / draft math changes.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => ({ authenticated: true, logout: vi.fn() }),
}));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeagueKey: "dynasty_main", loading: false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/draft",
  useSearchParams: () => new URLSearchParams(),
}));

import { NextBestTargets } from "@/app/draft/page";
import {
  marketAction,
  marketActionDisclosed,
  IDP_EDGE_DISCLOSURE_TITLE,
} from "@/lib/display-helpers";
import { rowMatches } from "@/lib/player-filters";

const IDP = {
  name: "Abdul Carter",
  assetClass: "idp",
  position: "DL",
  marketGapDirection: "none",
  marketGapValueRatio: null,
  ktcMarket: { value: null, available: false, reason: "no_ktc_coverage" },
  rankDerivedValue: 4407,
};
const OFFENSE_SELL = {
  name: "Offense Sell",
  assetClass: "offense",
  position: "WR",
  marketGapDirection: "retail_premium",
  marketGapValueRatio: 0.2,
  ktcMarket: { value: 5000, normalizedValue: 5000, available: true },
  rankDerivedValue: 4000,
};

describe("W27-F001 disclosure", () => {
  it("IDP rows get an explicit offense-only state pointing to /edge", () => {
    const a = marketActionDisclosed(IDP);
    expect(a.label).toBe("offense only");
    expect(a.title).toBe(IDP_EDGE_DISCLOSURE_TITLE);
    expect(a.title).toContain("/edge");
    expect(a.css).toBe("edge-none");
  });
  it("offense rows are identical to marketAction", () => {
    expect(marketActionDisclosed(OFFENSE_SELL)).toEqual(marketAction(OFFENSE_SELL));
    expect(marketActionDisclosed(OFFENSE_SELL).label).toBe("SELL");
  });
  it("underlying detector/filter unchanged (still no IDP verdict)", () => {
    expect(marketAction(IDP).label).toBe("—");
    expect(rowMatches(IDP, { edge: "sell" })).toBe(false);
  });
});

describe("W10-F003 empty Next Best Targets", () => {
  it("explains why it is empty and points to Perfect Draft", () => {
    render(
      <NextBestTargets
        stats={{ enrichedPlayers: [] }}
        onDraft={() => {}}
        onCycleTag={() => {}}
      />,
    );
    const note = screen.getByTestId("nbt-empty-reason");
    expect(note.textContent).toMatch(/per-player gate/);
    expect(note.textContent).toMatch(/Perfect Draft/);
    expect(screen.getByText(/Nothing to flag yet/)).toBeTruthy();
  });
  it("non-empty panel is unchanged (no empty-state note)", () => {
    const p = {
      id: "p1",
      name: "Rookie One",
      tier: "A",
      drafted: false,
      userTag: null,
      inflatedFair: 40,
      myWinningBid: 10,
    };
    render(
      <NextBestTargets
        stats={{ enrichedPlayers: [p], tierStats: {} }}
        onDraft={() => {}}
        onCycleTag={() => {}}
      />,
    );
    expect(screen.queryByTestId("nbt-empty-reason")).toBeNull();
    expect(screen.getByText("Rookie One")).toBeTruthy();
  });
});

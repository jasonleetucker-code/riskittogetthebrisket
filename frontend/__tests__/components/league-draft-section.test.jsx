import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui", () => ({ PlayerImage: () => null, EmptyState: () => null }));

import DraftSection from "@/app/league/sections/draft";
import { pickChipKey } from "@/app/league/pick-chips";
import { SECTION_FOR_TAB, SUB_TABS } from "@/app/league/tabs";

// Two 2027 firsts on one manager — one his own, one acquired — must read as
// two different picks (the 2026-10-17 P0 screenshot showed "2027 R1*" x8).
function pick(season, round, origin, originName, traded) {
  return {
    assetId: `pick:dynasty_main:${season}:r${round}:o${origin}`,
    season,
    round,
    originRosterId: origin,
    originalOwnerId: `owner-${origin}`,
    originDisplayName: originName,
    originLabel: traded ? `From ${originName}` : "Own",
    isTraded: traded,
    label: `${season} R${round}`,
  };
}

const observed = {
  pickOwnershipState: "observed",
  pickOwnershipReason: null,
  stockpileLeaderboard: [
    { ownerId: "owner-1", displayName: "Jason", totalPicks: 3, weightedScore: 11 },
    { ownerId: "owner-2", displayName: "Kich", totalPicks: 1, weightedScore: 3 },
    { ownerId: "owner-3", displayName: "Joey", totalPicks: 0, weightedScore: 0 },
  ],
  pickOwnership: {
    "owner-1": [
      pick("2027", 1, 1, "Jason", false),
      pick("2027", 1, 3, "Joey", true),
      pick("2027", 2, 2, "Kich", true),
    ],
    "owner-2": [pick("2028", 2, 2, "Kich", false)],
    "owner-3": [],
  },
  mostTradedPick: {
    season: "2027",
    round: 1,
    label: "2027 R1",
    originDisplayName: "Joey",
    moveCount: 2,
    evidence: "completed_trades",
    coverage: "complete",
  },
  drafts: [],
};

function chips() {
  return within(screen.getByTestId("pick-chips"));
}

describe("DraftSection pick inventory", () => {
  it("names each pick's origin so same-round picks are distinguishable", () => {
    render(<DraftSection data={observed} initialOwner="owner-1" />);
    expect(chips().getByText(/Own/)).toBeInTheDocument();
    expect(chips().getByText(/From Joey/)).toBeInTheDocument();
    expect(chips().getByText(/From Kich/)).toBeInTheDocument();
    expect(screen.queryByText(/\*/)).toBeNull();
  });

  it("keys chips by canonical asset id and stamps it on the chip", () => {
    render(<DraftSection data={observed} initialOwner="owner-1" />);
    const ids = [...screen.getByTestId("pick-chips").children].map((el) => el.dataset.assetId);
    expect(ids).toEqual([
      "pick:dynasty_main:2027:r1:o1",
      "pick:dynasty_main:2027:r1:o3",
      "pick:dynasty_main:2027:r2:o2",
    ]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(pickChipKey({ season: "2027", round: 1, originRosterId: 4 })).toBe("2027-1-4");
  });

  it("shows the published counts and switches managers from the leaderboard", () => {
    const setOwner = vi.fn();
    render(<DraftSection data={observed} initialOwner="owner-1" setOwner={setOwner} />);
    expect(screen.getAllByTestId("pick-chips")[0].children).toHaveLength(3);
    fireEvent.click(screen.getByText("Kich"));
    expect(setOwner).toHaveBeenCalledWith("owner-2");
    expect(screen.getByText("Picks owned by Kich")).toBeInTheDocument();
    expect(chips().getByText(/2028 R2/)).toBeInTheDocument();
    expect(screen.getByTestId("pick-chips").children).toHaveLength(1);
  });

  it("keeps a zero-pick manager visible with an honest empty message", () => {
    render(<DraftSection data={observed} initialOwner="owner-3" />);
    expect(screen.getByText("Joey")).toBeInTheDocument();
    expect(screen.getByText(/Holds no picks/)).toBeInTheDocument();
  });

  it("wraps chips for narrow screens", () => {
    render(<DraftSection data={observed} initialOwner="owner-1" />);
    const box = screen.getByTestId("pick-chips");
    expect(box.style.flexWrap).toBe("wrap");
    const chip = box.children[0];
    expect(chip.style.maxWidth).toBe("100%");
    expect(chip.style.textOverflow).toBe("ellipsis");
  });

  it("describes the most-traded pick by completed trades", () => {
    render(<DraftSection data={observed} initialOwner="owner-1" />);
    expect(screen.getByText(/Moved in/).textContent).toMatch(/Moved in 2 completed trades/);
  });

  it("renders unknown ownership honestly — no board, no counts, no inventory", () => {
    const unavailable = {
      ...observed,
      pickOwnershipState: "unavailable",
      pickOwnershipReason: "traded_picks_fetch_failed",
      pickOwnership: null,
      stockpileLeaderboard: null,
      mostPicksOwned: null,
      fewestPicksOwned: null,
    };
    render(<DraftSection data={unavailable} initialOwner="owner-1" />);
    expect(screen.getByRole("status").textContent).toMatch(/Pick ownership unavailable/);
    expect(screen.getByRole("status").textContent).toMatch(/traded-picks feed could not be read/);
    expect(screen.queryByText("Weighted pick stockpile")).toBeNull();
    expect(screen.queryByTestId("pick-chips")).toBeNull();
    expect(screen.queryByText(/Holds no picks/)).toBeNull();
  });

  it("leaves the Draft Capital tab wired to its own data", () => {
    const keys = SUB_TABS.map((t) => t.key);
    expect(keys).toContain("draft");
    expect(keys).toContain("draft-capital");
    expect(SECTION_FOR_TAB.draft).toBe("draft");
    expect(SECTION_FOR_TAB["draft-capital"]).toBeUndefined();
  });
});

describe("pick-chips helpers shared by the franchise views", () => {
  it("reads unknown ownership off a franchise draftCapital block", async () => {
    const { draftOwnershipUnavailableReason } = await import("@/app/league/pick-chips");
    expect(
      draftOwnershipUnavailableReason({
        totalPicks: null,
        pickOwnershipState: "unavailable",
        pickOwnershipReason: "traded_picks_fetch_failed",
      }),
    ).toBe("traded_picks_fetch_failed");
    expect(draftOwnershipUnavailableReason({ totalPicks: 4, pickOwnershipState: "observed" })).toBeNull();
    // A payload served before this field existed is not "unknown".
    expect(draftOwnershipUnavailableReason({ totalPicks: 4 })).toBeNull();
  });
});

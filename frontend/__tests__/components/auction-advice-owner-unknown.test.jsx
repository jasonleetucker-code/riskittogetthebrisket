// 2026-11-16 verified sweep: auction-room Perfect Draft advice and lot owners.
//
// A won lot belongs to its CURRENT owner (`owner`, which follows in-room
// trades).  When the room does not state the owner of a sold lot, this seat's
// roster room is unknown, so advice is withheld — and the panel must say WHY,
// not show the generic "unavailable" line.
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/auction-client", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    auctionFetch: vi.fn(() =>
      Promise.resolve({
        context: { openRosterSpots: 3, cutLadder: { rungs: [] }, waiverValues: {}, waiverLadder: null },
        boardValues: {},
      }),
    ),
  };
});

import AuctionAdvicePanel from "@/components/auction/AuctionAdvicePanel";

const POOL = {
  a: { name: "Alpha", pos: "WR", value: 6000 },
  b: { name: "Bravo", pos: "RB", value: 3000 },
};

function view(auctions) {
  return {
    public: { rules: { rounds: 1 }, seats: [{ id: "S1" }, { id: "S2" }], total_opening_pool: 100, auctions },
    me: { seat: "S1", private: { balance: 50, committed: 0, spendable: 50 } },
  };
}

describe("AuctionAdvicePanel — a sold lot with no stated owner", () => {
  it("names the reason advice is withheld", async () => {
    const lot = { id: "A1", player: "a", status: "closed", price: 40, leader: null, winner: "S1" };
    render(<AuctionAdvicePanel view={view([lot])} pool={POOL} roomId="r1" />);
    expect(await screen.findByText(/did not say who currently owns every sold player/i)).toBeTruthy();
    expect(screen.queryByText("Advice is unavailable for this seat.")).toBeNull();
  });

  it("plans normally when every sold lot states its owner", async () => {
    const lot = { id: "A1", player: "a", status: "closed", price: 40, leader: null, winner: "S2", owner: "S1" };
    render(<AuctionAdvicePanel view={view([lot])} pool={POOL} roomId="r1" />);
    // Give the context fetch a tick; no owner-unknown notice may appear.
    await screen.findByText(/Perfect Draft — your private plan/);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/did not say who currently owns/i)).toBeNull();
  });
});

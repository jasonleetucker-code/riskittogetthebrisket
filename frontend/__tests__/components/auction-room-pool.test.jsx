// 2026-11-16 verified sweep: the auction room's rookie-pool fetch.
//
// The pool turns a lot's player id into a name and is what the Nominate list
// is built from.  It used to be fetched once, any failure swallowed into
// `null`: the Nominate list sat empty, every lot printed its raw player id as
// the player's name, nothing said why, and nothing retried.  These pin the
// failed state, the retry, and that a raw id is never shown as a name.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useParams: () => ({ roomId: "r1" }) }));

vi.mock("@/lib/auction-client", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    auctionFetch: vi.fn(),
    useAuctionRoom: vi.fn(),
    useNowTicker: () => 1_700_000_000_000,
  };
});

vi.mock("@/lib/auction-notify", () => ({
  refreshBinding: () => Promise.resolve(null),
  notifyApi: {
    inbox: () => Promise.resolve({ items: [] }),
    watch: () => Promise.resolve({ watched: [] }),
  },
}));

vi.mock("@/components/auction/AuctionAdvicePanel", () => ({ default: () => null }));

import AuctionRoomPage from "@/app/auction/[roomId]/page.jsx";
import { POOL_UNAVAILABLE_LABEL, rookieLabel, useRoomPool } from "@/app/auction/[roomId]/room-pool";
import { auctionFetch, useAuctionRoom } from "@/lib/auction-client";

// Raw ids are deliberately unlike names so a leak is unmistakable.
const POOL = {
  players: {
    "pid-love-0001": { name: "Jeremiyah Love", pos: "RB", value: 7000 },
    "pid-ward-0002": { name: "Cam Ward", pos: "QB", value: 6000 },
    "pid-tate-0003": { name: "Carnell Tate", pos: "WR", value: 5000 },
  },
};
const RAW_IDS = Object.keys(POOL.players);

function roomView() {
  return {
    revision: 3,
    roomNow: 1_700_000_000_000,
    serverNow: 1_700_000_000_000,
    clockOffset: 0,
    events: [{ revision: 2, idx: 0, type: "sold", data: { player: "pid-love-0001", seat: "S2", price: 12 } }],
    me: {
      seat: "S1",
      role: "manager",
      private: {
        balance: 50,
        committed: 0,
        spendable: 50,
        conditional_exposure: 0,
        my_bids: [],
        queue: { players: ["pid-tate-0003"], auto: false },
        on_clock: null,
        trades: [],
      },
    },
    public: {
      room_id: "r1",
      name: "Test room",
      room_type: "official",
      status: "running",
      paused: null,
      active_now: true,
      open_count: 1,
      rules: { max_open: 12, rounds: 6, auction_active_seconds: 3600, extension_active_seconds: 300 },
      window_text: "Open all day",
      window: { enabled: false },
      unconfirmed_rules: [],
      pool: { label: "2027 class", is_official_class: true },
      seats: [
        { id: "S1", name: "Alpha", balance: 50, committed: 0, won: 0, rights_left: 6 },
        { id: "S2", name: "Beta", balance: 38, committed: 0, won: 1, rights_left: 6 },
      ],
      order: ["S1", "S2"],
      total_opening_pool: 100,
      auctions: [
        {
          id: "A1",
          player: "pid-ward-0002",
          nominator: "S2",
          round: 1,
          status: "open",
          price: 3,
          leader: "S2",
          winner: null,
          owner: null,
          deadline: 1_700_000_360_000,
          remaining_active_seconds: 360,
          closed_at: null,
          extensions: 0,
        },
        {
          id: "A2",
          player: "pid-love-0001",
          nominator: "S1",
          round: 1,
          status: "closed",
          price: 12,
          leader: null,
          winner: "S2",
          owner: "S2",
          deadline: 1_699_999_000_000,
          remaining_active_seconds: 0,
          closed_at: 1_699_999_000_000,
          extensions: 0,
        },
      ],
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("auction room: the rookie pool fails visibly and can be retried", () => {
  it("shows a failed state with retry, never raw ids as names, then recovers on retry", async () => {
    vi.mocked(useAuctionRoom).mockReturnValue({ view: roomView(), sync: "live", error: null });
    let poolCalls = 0;
    vi.mocked(auctionFetch).mockImplementation(async (path) => {
      if (path === "/rooms/r1/pool") {
        poolCalls += 1;
        if (poolCalls === 1) throw new Error("Service unavailable");
        return POOL;
      }
      throw new Error(`unexpected ${path}`);
    });

    render(<AuctionRoomPage />);

    expect(await screen.findByText("The rookie pool did not load")).toBeInTheDocument();
    expect(screen.getByText("Rookie pool unavailable")).toBeInTheDocument();
    // A raw id is never shown as a player's name, anywhere on the page.
    for (const pid of RAW_IDS) expect(document.body.textContent).not.toContain(pid);
    expect(screen.getAllByText(POOL_UNAVAILABLE_LABEL).length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);

    expect(await screen.findByText("Cam Ward")).toBeInTheDocument();
    expect(poolCalls).toBe(2);
    expect(screen.queryByText("The rookie pool did not load")).not.toBeInTheDocument();
    expect(screen.queryByText(POOL_UNAVAILABLE_LABEL)).not.toBeInTheDocument();
    // Nominate list is populated from the pool (Carnell Tate is unnominated).
    expect(screen.getAllByText("Carnell Tate").length).toBeGreaterThan(0);
    for (const pid of RAW_IDS) expect(document.body.textContent).not.toContain(pid);
  });

  it("says the pool is loading rather than showing an empty nominate list", async () => {
    vi.mocked(useAuctionRoom).mockReturnValue({ view: roomView(), sync: "live", error: null });
    vi.mocked(auctionFetch).mockImplementation(() => new Promise(() => {}));
    render(<AuctionRoomPage />);
    expect(await screen.findByText("Loading the rookie pool…")).toBeInTheDocument();
    for (const pid of RAW_IDS) expect(document.body.textContent).not.toContain(pid);
  });
});

describe("rookieLabel", () => {
  it("prefers the pool name, then a server-sent name, else a placeholder — never the id", () => {
    expect(rookieLabel(POOL.players, "pid-love-0001", "ready")).toBe("Jeremiyah Love");
    expect(rookieLabel(null, "pid-love-0001", "failed", "Jeremiyah Love")).toBe("Jeremiyah Love");
    expect(rookieLabel(null, "pid-love-0001", "failed")).toBe(POOL_UNAVAILABLE_LABEL);
    expect(rookieLabel(null, "pid-love-0001", "loading")).not.toContain("pid-love-0001");
    expect(rookieLabel(POOL.players, "pid-missing", "ready")).not.toContain("pid-missing");
  });
});

describe("useRoomPool", () => {
  it("treats a response with no players as failed, not as an empty pool", async () => {
    vi.mocked(auctionFetch).mockResolvedValue({});
    const { result } = renderHook(() => useRoomPool("r1"));
    await waitFor(() => expect(result.current.status).toBe("failed"));
    expect(result.current.players).toBeNull();
  });

  it("retries on demand", async () => {
    vi.mocked(auctionFetch).mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce(POOL);
    const { result } = renderHook(() => useRoomPool("r1"));
    await waitFor(() => expect(result.current.status).toBe("failed"));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.players).toBe(POOL.players);
  });
});

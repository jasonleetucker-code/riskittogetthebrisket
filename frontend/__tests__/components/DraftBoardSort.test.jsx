/**
 * Draft board — sortable-header accessibility (R4 review, P2-3).
 *
 * The board's nine-ish sortable columns were bare `<th onClick>` with
 * an ASCII ▲/▼: not focusable, not activatable, announcing nothing —
 * so the draft board could only be sorted with a mouse.  (`grep -c
 * aria-sort frontend/app/draft/page.jsx` returned 0.)  The header now
 * borrows the ds table's semantics: a real <button> inside the <th>,
 * `aria-sort` on the <th>, and the shared sort glyph.
 *
 * Mounting the whole 5k-line page would drag in localStorage, Sleeper
 * sync, and the auth context, so this exercises the `RookieBoard`
 * component directly (exported for tests, same pattern as
 * `describeCustomMix` on the rankings page).
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

import { RookieBoard } from "@/app/draft/page";
import { buildBdvmIndex } from "@/lib/bdvm";

function player(id, name, rank, winBid, tier = "A") {
  return {
    id,
    name,
    rank,
    tier,
    pos: "WR",
    team: "MIN",
    drafted: false,
    mine: false,
    userTag: null,
    preDraft: 40,
    marketValue: 38,
    inflatedFair: 42,
    enforceUpTo: 44,
    myWinningBid: winBid,
    myMaxBid: winBid + 5,
    theoreticalMaxBid: winBid + 9,
    final: null,
    draftedTo: null,
  };
}

const PLAYERS = [
  player("p1", "Alpha Back", 1, 70),
  player("p2", "Bravo Wide", 2, 55),
  player("p3", "Charlie End", 3, 30),
];

function renderBoard(extraProps = {}) {
  const noop = () => {};
  return render(
    <RookieBoard
      {...extraProps}
      stats={{
        enrichedPlayers: PLAYERS,
        tierStats: {},
        inflation: 1,
        remainingBudget: 200,
      }}
      workspace={{ teams: [{ name: "Me" }, { name: "Rival" }] }}
      marketDollars={{}}
      onDraft={noop}
      onEditPreDraft={noop}
      onRemovePlayer={noop}
      onCycleTag={noop}
      searchInputRef={{ current: null }}
      selectedPlayerId={null}
      onSelectRow={noop}
      quickRecordingId={null}
      onQuickOpen={noop}
      onQuickSubmit={noop}
      onQuickCancel={noop}
      needSet={new Set()}
      showDrafted={false}
      onShowDraftedChange={noop}
      query=""
      onQueryChange={noop}
      tagFilter="all"
      onTagFilterChange={noop}
      onAdd={noop}
    />,
  );
}

/** Player names in render order (first cell after rank is the name). */
function boardOrder() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => {
      const cells = within(r).queryAllByRole("cell");
      return cells.length > 4 ? cells[4].textContent.trim() : null;
    })
    .filter(Boolean);
}

describe("draft board sortable headers", () => {
  it("every sortable column is a real button, not a bare th onClick", () => {
    renderBoard();
    for (const label of [
      "#",
      "Player",
      "PreDraft",
      "Fair",
      "Enforce",
      "Win at",
      "Max Bid",
      "Final",
    ]) {
      expect(
        screen.getByRole("button", { name: label }),
        `"${label}" header should be a focusable button`,
      ).toBeInTheDocument();
    }
  });

  it("stamps aria-sort on the active column and flips it on re-activation", async () => {
    const user = userEvent.setup();
    renderBoard();

    // Default sort is myWinningBid descending.
    expect(screen.getByRole("columnheader", { name: /Win at/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    const playerHeader = screen.getByRole("columnheader", { name: /Player/ });
    expect(playerHeader).not.toHaveAttribute("aria-sort");

    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(playerHeader).toHaveAttribute("aria-sort", "descending");
    // …and the previous column's stamp is cleared.
    expect(
      screen.getByRole("columnheader", { name: /Win at/ }),
    ).not.toHaveAttribute("aria-sort");

    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(playerHeader).toHaveAttribute("aria-sort", "ascending");
  });

  it("is keyboard-operable: Enter on a header sorts the board", async () => {
    const user = userEvent.setup();
    renderBoard();
    const before = boardOrder();
    expect(before.length).toBe(3);

    const btn = screen.getByRole("button", { name: "Player" });
    btn.focus();
    expect(btn).toHaveFocus(); // the old bare <th> could not hold focus
    await user.keyboard("{Enter}");

    expect(
      screen.getByRole("columnheader", { name: /Player/ }),
    ).toHaveAttribute("aria-sort", "descending");
    expect(boardOrder()).not.toEqual(before);
  });

  it("sorting actually reorders rows (behaviour preserved through the a11y fix)", async () => {
    const user = userEvent.setup();
    renderBoard();
    // default: myWinningBid desc -> 70, 55, 30
    expect(boardOrder()).toEqual(["Alpha Back", "Bravo Wide", "Charlie End"]);

    await user.click(screen.getByRole("button", { name: "Player" }));
    const desc = boardOrder();
    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(boardOrder()).toEqual([...desc].reverse());
  });
});

/**
 * BDVM Fund gap column — flag-gated join, same posture as the rankings
 * page: the column exists only when a bdvmIndex is supplied (endpoint
 * answered ok) and vanishes entirely without one.  Draft rows carry no
 * playerId, so the join is name-based via buildBdvmIndex's byName map.
 */
describe("draft board BDVM fund gap column", () => {
  // Real index built by the real helper — exercises the actual join
  // path, not a hand-rolled Map shape that could drift.
  const bdvmIndex = buildBdvmIndex({
    players: [
      {
        name: "Alpha Back",
        market: { gap: 512, marketValue: 4000 },
        tradeValue: { balanced: 4512 },
        signal: { signal: "BUY", reason: "market underprices profile" },
      },
      {
        name: "Bravo Wide",
        market: { gap: -240, marketValue: 3000 },
        tradeValue: { balanced: 2760 },
        signal: { signal: "SELL", reason: "aging curve" },
      },
      // Charlie End deliberately absent → unpriced, muted dash.
    ],
  });

  it("column is absent without an index and present with one", () => {
    const { unmount } = renderBoard();
    expect(screen.queryByRole("button", { name: "Fund gap" })).toBeNull();
    unmount();

    renderBoard({ bdvmIndex });
    expect(screen.getByRole("button", { name: "Fund gap" })).toBeInTheDocument();
  });

  it("shows signed gaps for priced rows and a dash for unpriced rows", () => {
    renderBoard({ bdvmIndex });
    expect(screen.getByText("+512")).toBeInTheDocument();
    expect(screen.getByText("−240")).toBeInTheDocument();
    // Charlie End has no fundamental value: his row's gap cell is a dash.
    const charlieRow = screen.getByText("Charlie End").closest("tr");
    const cells = within(charlieRow).getAllByRole("cell");
    // Fund gap sits right after Market (rank, tier, tag, rec, player,
    // preDraft, market, gap → index 7).
    expect(cells[7].textContent.trim()).toBe("—");
  });

  it("sorts by gap with unpriced rows sinking in both directions", async () => {
    const user = userEvent.setup();
    renderBoard({ bdvmIndex });

    await user.click(screen.getByRole("button", { name: "Fund gap" }));
    // Descending: +512, −240, then unpriced sinks.
    expect(boardOrder()).toEqual(["Alpha Back", "Bravo Wide", "Charlie End"]);

    await user.click(screen.getByRole("button", { name: "Fund gap" }));
    // Ascending: −240, +512 — unpriced STILL last.
    expect(boardOrder()).toEqual(["Bravo Wide", "Alpha Back", "Charlie End"]);
  });
});

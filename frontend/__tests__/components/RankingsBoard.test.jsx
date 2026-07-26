/**
 * RankingsPage (R2 board) — load-bearing path coverage.
 *
 * The board is the highest-traffic surface in the app and, before this
 * file, had ZERO automated coverage: the Playwright journey suite is
 * the only thing that renders it, and that suite was red on main
 * (R1 selector drift, repaired in this PR) so it had never validated
 * the R2 board at all.  This is the focused net for the four paths a
 * board rewrite can silently break:
 *
 *   1. rows render from a contract fixture (the materializer path)
 *   2. clicking a column header re-orders the board (+ aria-sort)
 *   3. the position filter narrows the row set
 *   4. clicking a row expands the source-audit panel
 *
 * Deliberately NOT exhaustive — this covers the spine, not every lens,
 * export, and popover on a 1,050-line page.
 *
 * The page is wired through eight hooks; they're mocked to controlled
 * defaults so the assertions exercise the PAGE's own logic (filter →
 * sort → limit → render) rather than the data layer underneath it.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Fixture board: 4 offense rows across 3 positions ───────────────
// Shaped like buildRows() output — backend stamps included, because
// the board renders stamps verbatim and must never recompute them.
function boardRow(name, pos, rank, value, extra = {}) {
  return {
    name,
    displayName: name,
    canonicalName: name,
    pos,
    position: pos,
    team: extra.team || "MIN",
    assetClass: "offense",
    rookie: false,
    rank,
    canonicalConsensusRank: rank,
    blendedSourceRank: rank + 0.4,
    rankDerivedValue: value,
    values: { full: value },
    sourceCount: 4,
    siteCount: 4,
    confidenceBucket: "high",
    canonicalTierId: 1,
    sourceRanks: { ktcSfTep: rank, fantasycalc: rank },
    sourceRankMeta: {
      ktcSfTep: { valueContribution: value, method: "value_direct" },
      fantasycalc: { valueContribution: value - 40, method: "hill" },
    },
    canonicalSites: { ktcSfTep: value, fantasycalc: value - 40 },
    sourceAudit: {
      reason: "fully_matched",
      expectedSources: ["ktcSfTep", "fantasycalc"],
      matchedSources: ["ktcSfTep", "fantasycalc"],
      unmatchedSources: [],
    },
    raw: { team: extra.team || "MIN", playerId: extra.playerId || `id-${name}` },
    ...extra,
  };
}

const ROWS = [
  boardRow("Justin Jefferson", "WR", 1, 9541),
  boardRow("Bijan Robinson", "RB", 2, 9155, { team: "ATL" }),
  boardRow("Josh Allen", "QB", 3, 8900, { team: "BUF" }),
  boardRow("Amon-Ra St. Brown", "WR", 4, 8700, { team: "DET" }),
];

const openPlayerPopup = vi.fn();

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    source: "test",
    rows: ROWS,
    rawData: { dataFreshness: { generatedAt: "2026-07-26T00:00:00Z" } },
  }),
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ openPlayerPopup, rows: ROWS, rawData: {} }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({
    settings: { showSiteCols: false, hiddenSiteCols: {}, siteWeights: {} },
    update: vi.fn(),
    updateSiteWeight: vi.fn(),
    resetSiteWeights: vi.fn(),
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ idpEnabled: true, selectedLeagueKey: "dynasty_main" }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: { watchlist: [] },
    toggleWatchlist: vi.fn(),
    serverBacked: false,
  }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ byPlayer: new Map(), digestByPlayer: new Map() }),
}));
// Chart children fetch / measure — stub to keep the test on the board.
vi.mock("@/components/graphs/HillCurveExplorer", () => ({ default: () => null }));
vi.mock("@/components/graphs/TierGapWaterfall", () => ({ default: () => null }));
vi.mock("@/components/graphs/RankChangeGlyph", () => ({ default: () => null }));
vi.mock("@/components/graphs/SourceContributionBars", () => ({ default: () => null }));
vi.mock("@/components/graphs/SourceAgreementRadar", () => ({ default: () => null }));

import RankingsPage from "@/app/rankings/page";

/** Player names in render order, from the board's name cells. */
function renderedNames() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => {
      const btn = within(r).queryByTitle(/Open .* profile/);
      return btn ? btn.textContent.trim() : null;
    })
    .filter(Boolean);
}

beforeEach(() => {
  openPlayerPopup.mockClear();
});

describe("rankings board", () => {
  it("renders a row per eligible player, in backend rank order", () => {
    render(<RankingsPage />);
    expect(renderedNames()).toEqual([
      "Justin Jefferson",
      "Bijan Robinson",
      "Josh Allen",
      "Amon-Ra St. Brown",
    ]);
    // backend stamps render verbatim — value + consensus, not recomputed
    const firstRow = screen.getAllByRole("row")[1];
    expect(firstRow).toHaveTextContent("9,541");
    expect(firstRow).toHaveTextContent("1.4");
  });

  it("sorting by Player re-orders the board and stamps aria-sort", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.click(screen.getByRole("button", { name: "Player" }));

    expect(renderedNames()).toEqual([
      "Amon-Ra St. Brown",
      "Bijan Robinson",
      "Josh Allen",
      "Justin Jefferson",
    ]);
    expect(screen.getByRole("columnheader", { name: "Player" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    // second activation flips direction (the audit's zero-aria-sort fix)
    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(renderedNames()).toEqual([
      "Justin Jefferson",
      "Josh Allen",
      "Bijan Robinson",
      "Amon-Ra St. Brown",
    ]);
    expect(screen.getByRole("columnheader", { name: "Player" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("the position filter narrows the board to one position", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    expect(renderedNames()).toHaveLength(4);

    await user.selectOptions(screen.getByLabelText("Position filter"), "WR");
    expect(renderedNames()).toEqual(["Justin Jefferson", "Amon-Ra St. Brown"]);

    // and restores when cleared
    await user.selectOptions(screen.getByLabelText("Position filter"), "all");
    expect(renderedNames()).toHaveLength(4);
  });

  it("clicking a row expands the source-audit panel; clicking again collapses", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    expect(screen.queryByText(/Source Audit:/)).toBeNull();

    // click the row itself (not the name button, which opens the profile)
    const firstRow = screen.getAllByRole("row")[1];
    await user.click(within(firstRow).getByText("WR"));

    const audit = screen.getByText(/Source Audit: Justin Jefferson/);
    expect(audit).toBeInTheDocument();
    // the panel renders the backend audit verdict verbatim
    expect(
      screen.getByText(/All expected sources matched/),
    ).toBeInTheDocument();
    // …and keeps the legacy inset styling hook
    expect(document.querySelector("tr.rankings-audit-row")).not.toBeNull();

    await user.click(within(screen.getAllByRole("row")[1]).getByText("WR"));
    expect(screen.queryByText(/Source Audit:/)).toBeNull();
  });

  it("a player-name click opens the profile instead of expanding the row", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.click(screen.getByTitle("Open Josh Allen's profile"));
    expect(openPlayerPopup).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Josh Allen" }),
    );
    expect(screen.queryByText(/Source Audit:/)).toBeNull();
  });

  it("an over-narrow filter shows the empty state, not a blank panel", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.type(screen.getByLabelText("Search the board"), "zzzznobody");
    expect(screen.getByText(/No players match these filters/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Reset filters/ }),
    ).toBeInTheDocument();
  });
});

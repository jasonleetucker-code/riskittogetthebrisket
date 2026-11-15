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
const bdvm = vi.hoisted(() => ({ data: null, request: vi.fn() }));
vi.mock("@/components/useBdvm", () => ({ useBdvmEndpoint: (...args) => {
  bdvm.request(...args);
  return { data: bdvm.data, failure: null };
} }));

const DEFAULT_RAW_DATA = {
  dataFreshness: { generatedAt: "2026-07-26T00:00:00Z" },
  // Board built from an EARLIER scrape — the two clocks differ.
  scrapeTimestamp: "2026-07-25T18:00:00Z",
};
// ``rows`` lets one describe swap in its own board without touching the
// shared 4-row fixture the rest of this file asserts against.
const dyn = vi.hoisted(() => ({ rawData: null, rows: null }));
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    source: "test",
    rows: dyn.rows || ROWS,
    rawData: dyn.rawData || DEFAULT_RAW_DATA,
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
  dyn.rawData = null;
  dyn.rows = null;
  openPlayerPopup.mockClear();
  bdvm.data = null;
  bdvm.request.mockClear();
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

  // C8-U2 2026-09-29: the expanded row rendered through the legacy
  // `source-audit-*` globals — the retired dark terminal palette — and
  // measured 283 axe color-contrast nodes at 1366px on the live board.
  it("the expanded audit panel renders on the editorial module, not the legacy dark classes", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.click(within(screen.getAllByRole("row")[1]).getByText("WR"));
    expect(document.querySelector(".source-audit-panel")).toBeNull();
    expect(document.querySelector("[class*='source-audit-']")).toBeNull();
    const auditRow = document.querySelector("tr.rankings-audit-row");
    expect(auditRow.className).toMatch(/auditRow/);
  });

  it("names the board-built and scrape clocks instead of calling build time 'Last scraped'", () => {
    render(<RankingsPage />);
    expect(screen.queryByText(/Last scraped/)).toBeNull();
    expect(screen.getByText(/Board built/)).toBeInTheDocument();
    expect(screen.getByText(/from the scrape of/)).toBeInTheDocument();
  });

  it("never presents the board BUILD time as an update: header names the scrape clock", () => {
    // Board rebuilt just now (e.g. a restart) from a scrape 3 days old.
    const now = Date.now();
    dyn.rawData = {
      dataFreshness: { generatedAt: new Date(now).toISOString() },
      scrapeTimestamp: new Date(now - 3 * 86_400_000).toISOString(),
    };
    render(<RankingsPage />);
    const header = document.body.textContent;
    expect(header).not.toMatch(/Updated/);
    expect(screen.getByText("Chase Upside Consensus / Scraped 3d ago")).toBeInTheDocument();
  });

  it("falls back to the build clock, labelled as the build clock, when no scrape time is published", () => {
    const now = Date.now();
    dyn.rawData = { dataFreshness: { generatedAt: new Date(now - 2 * 3_600_000).toISOString() } };
    render(<RankingsPage />);
    expect(screen.getByText("Chase Upside Consensus / Board built 2h ago")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Updated/);
  });

  it("describes confidence with the current rule, not the retired spread rule", () => {
    render(<RankingsPage />);
    expect(screen.queryByText("2+ src, tight")).toBeNull();
    expect(screen.getAllByRole("button", { name: "What is confidence?" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "What is Value?" })).toBeInTheDocument();
  });

  it("keeps the primary value on the phone board: Consensus (a diagnostic) hides below md", () => {
    render(<RankingsPage />);
    const firstRow = screen.getAllByRole("row")[1];
    expect(firstRow.querySelector("td[data-col='score']").className).toMatch(/ds-col-hide-md/);
    expect(firstRow.querySelector("td[data-col='value']").className).not.toMatch(/ds-col-hide/);
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


it("opts only rankings into board and preserves full/board gap display, sorting and CSV", async () => {
  const user = userEvent.setup();
  const players = ROWS.map((row, i) => ({playerId:row.raw.playerId, name:row.name,
    market:{gap:[10,0,null,-20][i],marketValue:100}, tradeValue:{balanced:110,contender:120},
    signal:{signal:"BUY",reason:i===2?"no anchor":"backend reason"},projection:{anyProxy:i===0,fpg:12},raw:{privateDetail:"unused"}}));
  const full={status:"ok",players};
  const board={...full,players:players.map(p=>({playerId:p.playerId,name:p.name,market:p.market,
    tradeValue:{balanced:p.tradeValue.balanced},signal:p.signal,projection:{anyProxy:p.projection.anyProxy}}))};
  const csvs=[];
  const create = vi.fn(blob=>{csvs.push(blob);return "blob:test"});
  vi.stubGlobal("URL",Object.assign(URL,{createObjectURL:create,revokeObjectURL:vi.fn()}));
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
  const outputs=[];
  try {
    for(const payload of [full,board]) {
      bdvm.data=payload;
      const mounted=render(<RankingsPage/>);
      expect(bdvm.request).toHaveBeenLastCalledWith("/api/bdvm/values",{params:{view:"board"}});
      expect(screen.getByText("+10*").title).toContain("PROXY: fundamental is the reconstructed baseline");
      expect(screen.getByTitle("no anchor")).toHaveTextContent("—");
      await user.click(screen.getByRole("button",{name:"Fund gap"}));
      const names=renderedNames();
      await user.click(screen.getByRole("button",{name:"Export CSV"}));
      const text=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsText(csvs.at(-1));});
      outputs.push({names,text,proxy:screen.getByText("+10*").title});
      expect(names.at(-1)).toBe("Josh Allen");
      expect(text.split("\n").slice(1).map(line=>line.split(",")[1])).toEqual(names);
      mounted.unmount();
    }
    expect(outputs[1]).toEqual(outputs[0]);
  } finally {click.mockRestore();vi.unstubAllGlobals();}
});

it("labels the Fund gap column's fundamental side as provisional BDVM, not the market board", async () => {
  const user = userEvent.setup();
  bdvm.data = {
    status: "ok",
    players: ROWS.map((row) => ({
      playerId: row.raw.playerId,
      name: row.name,
      market: { gap: 10, marketValue: 100 },
      tradeValue: { balanced: 110 },
      signal: { signal: "BUY", reason: "backend reason" },
      projection: { anyProxy: false },
    })),
  };
  render(<RankingsPage />);
  const trigger = screen.getByRole("button", { name: "What is Fund gap?" });
  trigger.focus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("region", { name: "Fund gap" })).toHaveTextContent(
    "Fundamental value (BDVM) · provisional priors — not the market board.",
  );
});

// ── NFL team filter in the MAIN control bar ───────────────────────────
// The select is bound to ``adv.nflTeam`` — the same single state and the
// same ``rowMatches`` pass the advanced rail used — so these tests check
// the control's placement, its one-state design, how it composes with the
// other filters, and the board invariant that filtering HIDES rows and
// never re-ranks them (ranks are backend ``canonicalConsensusRank``
// stamps; ``buildRows`` is a pure materializer).
describe("NFL team filter (main control bar)", () => {
  // Deliberately non-contiguous ranks: any client-side renumbering of a
  // filtered view (1, 2, 3 …) would be visible against these stamps.
  const TEAM_ROWS = [
    boardRow("Justin Jefferson", "WR", 1, 9541, { team: "MIN", age: 26 }),
    boardRow("Josh Allen", "QB", 3, 8900, { team: "BUF", age: 29 }),
    boardRow("Brock Bowers", "TE", 12, 7400, { team: "LV", age: 23 }),
    boardRow("George Pickens", "WR", 18, 6900, { team: "PIT", age: 25, confidenceBucket: "medium" }),
    boardRow("T.J. Hockenson", "TE", 29, 6100, { team: "MIN", age: 28 }),
    boardRow("Jordan Addison", "WR", 41, 5200, { team: "MIN", age: 24, confidenceBucket: "low" }),
    boardRow("Null Team Guy", "WR", 90, 3000, { team: null, age: 27 }),
    boardRow("Empty Team Guy", "RB", 95, 2900, { team: "", age: 27 }),
    boardRow("Free Agent Guy", "RB", 99, 2800, { team: "FA", age: 27 }),
  ];
  const ALL_NAMES = TEAM_ROWS.map((r) => r.name);

  const teamSelect = () => screen.getByLabelText("NFL team filter");
  /** The ``aria-live`` result line ("N shown · ...") a screen reader announces. */
  const resultLine = () =>
    Array.from(document.querySelectorAll('[aria-live="polite"]')).find((el) =>
      /shown/.test(el.textContent),
    );

  /** [name, rank, value] per rendered row, read from the table cells. */
  function boardCells() {
    return screen
      .getAllByRole("row")
      .slice(1)
      .map((r) => {
        const btn = within(r).queryByTitle(/Open .* profile/);
        if (!btn) return null;
        // The "#" cell also hosts the row-disclosure button's hidden label,
        // so read the rank span itself (what a user sees as the number).
        const rank = r
          .querySelector("td[data-col='rank'] [class*='rankCell']")
          ?.textContent.trim();
        const value = r.querySelector("td[data-col='value']")?.textContent.replace(/[^\d]/g, "");
        return [btn.textContent.trim(), Number(rank), Number(value)];
      })
      .filter(Boolean);
  }
  const stampOf = (name) => {
    const r = TEAM_ROWS.find((x) => x.name === name);
    return [r.name, r.canonicalConsensusRank, r.rankDerivedValue];
  };

  beforeEach(() => {
    dyn.rows = TEAM_ROWS;
  });

  it("is visible in the main control bar without opening Advanced Filters, defaulting to All NFL Teams", () => {
    render(<RankingsPage />);
    const select = teamSelect();
    expect(select).toBeInTheDocument();
    expect(select.tagName).toBe("SELECT");
    expect(select).toHaveValue("");
    expect(select).toHaveDisplayValue("All NFL Teams");
    // It sits in the same bar as search / position / confidence, and the
    // advanced rail is still closed.
    expect(select.closest(".rankings-controls")).not.toBeNull();
    expect(screen.getByLabelText("Position filter").closest(".rankings-controls")).toBe(
      select.closest(".rankings-controls"),
    );
    expect(screen.getByRole("button", { name: /^Filters/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Experience")).toBeNull();
    // Nothing selected, so nothing to clear.
    expect(screen.queryByRole("button", { name: /^Clear team/ })).toBeNull();
    expect(renderedNames()).toEqual(ALL_NAMES);
  });

  it("offers the board's own team codes (the teamOptions source), not a second list", async () => {
    render(<RankingsPage />);
    const { teamOptions } = await import("@/lib/player-filters");
    const values = within(teamSelect())
      .getAllByRole("option")
      .map((o) => o.getAttribute("value"));
    expect(values).toEqual(["", ...teamOptions(TEAM_ROWS)]);
    // Spelled out for readability: FA last, unknown (null / "") teams never an option.
    expect(values).toEqual(["", "BUF", "LV", "MIN", "PIT", "FA"]);
    expect(within(teamSelect()).getByRole("option", { name: "Free agent (NFL)" })).toHaveValue("FA");
    expect(within(teamSelect()).getByRole("option", { name: "All NFL Teams" })).toHaveValue("");
  });

  it("is the ONLY NFL team control: opening Filters does not render a second one", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    expect(screen.getAllByRole("combobox", { name: /NFL team/i })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /^Filters/ }));
    // The rail is open (its own controls are there)…
    expect(screen.getByLabelText("Experience")).toBeInTheDocument();
    // …but there is still exactly one team select, and it is the main-bar one.
    const teams = screen.getAllByRole("combobox", { name: /NFL team/i });
    expect(teams).toHaveLength(1);
    expect(teams[0].closest(".rankings-controls")).not.toBeNull();
    expect(screen.queryByText("Any NFL team")).toBeNull();
  });

  it("selecting a team immediately shows only that franchise, with each player's real rank and value", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "MIN");

    expect(teamSelect()).toHaveValue("MIN");
    expect(renderedNames()).toEqual(["Justin Jefferson", "T.J. Hockenson", "Jordan Addison"]);
    // Backend stamps verbatim: ranks 1 / 29 / 41, NOT renumbered 1 / 2 / 3.
    expect(boardCells()).toEqual([
      stampOf("Justin Jefferson"),
      stampOf("T.J. Hockenson"),
      stampOf("Jordan Addison"),
    ]);
    expect(boardCells().map(([, rank]) => rank)).toEqual([1, 29, 41]);

    // Other franchises, same invariant — a lone survivor keeps its own rank.
    await user.selectOptions(teamSelect(), "LV");
    expect(boardCells()).toEqual([stampOf("Brock Bowers")]);
    await user.selectOptions(teamSelect(), "PIT");
    expect(boardCells()).toEqual([stampOf("George Pickens")]);
  });

  it("hides players with a null, empty or FA team once a franchise is selected, and shows them under All", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    const unknown = ["Null Team Guy", "Empty Team Guy", "Free Agent Guy"];
    expect(renderedNames()).toEqual(expect.arrayContaining(unknown));

    for (const team of ["MIN", "BUF", "LV", "PIT"]) {
      await user.selectOptions(teamSelect(), team);
      for (const name of unknown) expect(renderedNames()).not.toContain(name);
    }

    // FA is its own explicit option — free agents only, never the unknown rows.
    await user.selectOptions(teamSelect(), "FA");
    expect(renderedNames()).toEqual(["Free Agent Guy"]);

    await user.selectOptions(teamSelect(), "");
    expect(renderedNames()).toEqual(ALL_NAMES);
  });

  it("combines with position, search, confidence, a lens and the advanced filters", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "MIN");

    // position
    await user.selectOptions(screen.getByLabelText("Position filter"), "WR");
    expect(renderedNames()).toEqual(["Justin Jefferson", "Jordan Addison"]);
    await user.selectOptions(screen.getByLabelText("Position filter"), "TE");
    expect(renderedNames()).toEqual(["T.J. Hockenson"]);
    await user.selectOptions(screen.getByLabelText("Position filter"), "all");

    // search — cannot widen past the team (PIT's Pickens stays out)
    await user.type(screen.getByLabelText("Search the board"), "jordan");
    expect(renderedNames()).toEqual(["Jordan Addison"]);
    await user.clear(screen.getByLabelText("Search the board"));
    await user.type(screen.getByLabelText("Search the board"), "pickens");
    expect(screen.getByText(/No players match these filters/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Search the board"));
    expect(renderedNames()).toHaveLength(3);

    // confidence ("low" bucket → only Addison)
    await user.selectOptions(screen.getByLabelText("Confidence filter"), "low");
    expect(renderedNames()).toEqual(["Jordan Addison"]);
    await user.selectOptions(screen.getByLabelText("Confidence filter"), "all");

    // lens ("Safest": high confidence + 2 sources → drops low-confidence Addison)
    await user.click(screen.getByRole("tab", { name: "Safest" }));
    expect(renderedNames()).toEqual(["Justin Jefferson", "T.J. Hockenson"]);
    await user.click(screen.getByRole("tab", { name: "Consensus" }));
    expect(renderedNames()).toHaveLength(3);

    // advanced filter (Age min 25 → drops 24-year-old Addison); team still binds
    await user.click(screen.getByRole("button", { name: /^Filters/ }));
    await user.type(screen.getAllByPlaceholderText("min")[0], "25");
    expect(renderedNames()).toEqual(["Justin Jefferson", "T.J. Hockenson"]);
    expect(teamSelect()).toHaveValue("MIN");

    // ranks are still the stamps through every combination
    expect(boardCells()).toEqual([stampOf("Justin Jefferson"), stampOf("T.J. Hockenson")]);
  });

  it("All NFL Teams restores the full board in canonical rank order", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "MIN");
    expect(renderedNames()).toHaveLength(3);

    await user.selectOptions(teamSelect(), "All NFL Teams");
    expect(teamSelect()).toHaveValue("");
    expect(boardCells()).toEqual(TEAM_ROWS.map((r) => stampOf(r.name)));
  });

  it("shows a Clear team control only while a team is selected, and it resets the select and the board", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    expect(screen.queryByRole("button", { name: /^Clear team/ })).toBeNull();

    await user.selectOptions(teamSelect(), "MIN");
    const clear = screen.getByRole("button", { name: /^Clear team/ });
    // It lives in the same flex item as the select, so it cannot wrap away from it.
    expect(clear.parentElement).toBe(teamSelect().closest("span[class*='controlsTeam']"));
    // The result line names the active team.
    expect(resultLine().textContent).toMatch(/shown · NFL team MIN/);

    await user.click(clear);
    expect(teamSelect()).toHaveValue("");
    expect(screen.queryByRole("button", { name: /^Clear team/ })).toBeNull();
    expect(renderedNames()).toEqual(ALL_NAMES);
    expect(resultLine().textContent).not.toMatch(/NFL team/);
  });

  // WCAG 2.5.3 (Label in Name): a voice-control user says what they SEE, so
  // the accessible name has to start with the visible text.  The team goes
  // after it, for context.
  it("the Clear button's accessible name starts with its visible text", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "MIN");
    const clear = screen.getByRole("button", { name: /^Clear team/ });
    expect(clear).toHaveTextContent("Clear team");
    expect(clear).toHaveAccessibleName("Clear team (MIN)");
    // Nothing in the old, longer wording survives to confuse a name match.
    expect(screen.queryByRole("button", { name: /Clear NFL team filter/ })).toBeNull();
  });

  // The button unmounts the instant the filter clears; without an explicit
  // hand-off, focus falls to <body> and a keyboard user loses their place.
  it("returns focus to the NFL team select after Clear team (keyboard path included)", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "MIN");

    const clear = screen.getByRole("button", { name: /^Clear team/ });
    clear.focus();
    expect(clear).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("button", { name: /^Clear team/ })).toBeNull();
    expect(teamSelect()).toHaveValue("");
    expect(teamSelect()).toHaveFocus();
    expect(document.body).not.toHaveFocus();

    // Same hand-off on the pointer path.
    await user.selectOptions(teamSelect(), "BUF");
    await user.click(screen.getByRole("button", { name: /^Clear team/ }));
    expect(teamSelect()).toHaveFocus();
  });

  it("announces the active team in the live region as 'NFL team <code>', not a bare code", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    expect(resultLine()).toHaveAttribute("aria-live", "polite");
    expect(resultLine().textContent).not.toMatch(/NFL team/);

    await user.selectOptions(teamSelect(), "MIN");
    expect(resultLine().textContent).toMatch(/shown · NFL team MIN(?: ·|$)/);
    // The old bare " · MIN" suffix is gone.
    expect(resultLine().textContent).not.toMatch(/shown · MIN/);

    // The free-agent sentinel reads as words, not "NFL team Free agent (NFL)".
    await user.selectOptions(teamSelect(), "FA");
    expect(resultLine().textContent).toMatch(/shown · NFL free agents(?: ·|$)/);
  });

  // A data refresh or the IDP toggle can drop a code out of ``teamOptions``
  // while ``adv.nflTeam`` still holds it.  A controlled <select> whose value
  // matches no <option> silently displays the FIRST option ("All NFL
  // Teams") — it would claim "no filter" over a board the filter is
  // emptying.
  it("keeps a stale selected team visible and selected when it leaves the options", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "MIN");
    expect(renderedNames()).toHaveLength(3);

    // Data refresh: the board no longer carries a single MIN player.
    dyn.rows = TEAM_ROWS.filter((r) => r.team !== "MIN");
    rerender(<RankingsPage />);

    const optionValues = () =>
      within(teamSelect())
        .getAllByRole("option")
        .map((o) => o.getAttribute("value"));
    expect(teamSelect()).toHaveValue("MIN");
    expect(teamSelect()).toHaveDisplayValue("MIN");
    expect(teamSelect()).not.toHaveDisplayValue("All NFL Teams");
    // The board's own codes plus the one stale code — once, not a second list.
    const values = optionValues();
    expect(values.filter((v) => v === "MIN")).toHaveLength(1);
    expect([...values].sort()).toEqual(["", "BUF", "FA", "LV", "MIN", "PIT"].sort());
    expect(values.slice(0, 1)).toEqual([""]);
    // The filter is genuinely still active, which is the point of showing it.
    expect(screen.getByText(/No players match these filters/)).toBeInTheDocument();
    expect(resultLine().textContent).toMatch(/NFL team MIN/);

    // It can be cleared, and clearing drops the extra option again.
    await user.click(screen.getByRole("button", { name: /^Clear team/ }));
    expect(teamSelect()).toHaveValue("");
    expect(teamSelect()).toHaveDisplayValue("All NFL Teams");
    expect(optionValues()).not.toContain("MIN");
    expect(renderedNames()).toEqual(dyn.rows.map((r) => r.name));
  });

  it("adds no extra option when the selected team is still on the board", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "PIT");
    const values = within(teamSelect())
      .getAllByRole("option")
      .map((o) => o.getAttribute("value"));
    expect(values).toEqual(["", "BUF", "LV", "MIN", "PIT", "FA"]);
  });

  it("the clear-all control (Reset filters) clears the team along with every other filter", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    await user.selectOptions(teamSelect(), "BUF");
    await user.selectOptions(screen.getByLabelText("Position filter"), "RB");
    // BUF has no RB → empty state, which carries the reset action.
    expect(screen.getByText(/No players match these filters/)).toBeInTheDocument();
    expect(screen.getByText(/Clear the search, NFL team or advanced filters/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Reset filters/ }));
    expect(teamSelect()).toHaveValue("");
    expect(screen.getByLabelText("Position filter")).toHaveValue("all");
    expect(renderedNames()).toEqual(ALL_NAMES);
  });

  it("keeps the Filters badge consistent: the team is not counted as a rail filter, and the rail's Clear leaves it alone", async () => {
    const user = userEvent.setup();
    render(<RankingsPage />);
    const filtersBtn = () => screen.getByRole("button", { name: /^Filters/ });

    // Team alone: the rail holds nothing active, so no badge and no rail Clear.
    await user.selectOptions(teamSelect(), "MIN");
    expect(filtersBtn()).toHaveTextContent(/^Filters$/);
    await user.click(filtersBtn());
    expect(screen.queryByTitle("Clear advanced filters")).toBeNull();

    // A rail filter adds exactly one to the badge, team or not.
    await user.type(screen.getAllByPlaceholderText("min")[0], "25");
    expect(filtersBtn()).toHaveTextContent(/^Filters \(1\)$/);
    expect(renderedNames()).toEqual(["Justin Jefferson", "T.J. Hockenson"]);

    // The rail's Clear resets the rail only; the visible team control keeps its state.
    await user.click(screen.getByTitle("Clear advanced filters"));
    expect(filtersBtn()).toHaveTextContent(/^Filters$/);
    expect(teamSelect()).toHaveValue("MIN");
    expect(renderedNames()).toEqual(["Justin Jefferson", "T.J. Hockenson", "Jordan Addison"]);
  });
});

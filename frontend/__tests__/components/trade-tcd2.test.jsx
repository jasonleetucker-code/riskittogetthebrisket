/**
 * TC-D2 (+ the TC-B2 rows that render on /trade).
 *
 * Pieces:
 *   - TradePackageBreakdown (M01 / M02 / M04 / M05): bars + legend + facts,
 *     every number printed, VA its own segment, missing never 0;
 *   - TradeDecisionReasoning: the decision's own whatWouldChange + coverage,
 *     verbatim, all ten dimensions;
 *   - TradeIntelTabs: ONLY the active panel is rendered (no chunk, no request
 *     for a closed tab);
 *   - MultiTeamSummaryBar: the multi-team meter's own nets and band.
 * The page:
 *   - no "Market / My league" control (D09);
 *   - CSV / JSON / Copy KTC URL live in a "More" group; Simulate impact is in
 *     the Roster tab, not the toolbar (H13);
 *   - phones build through one bottom sheet per side;
 *   - a 3+-team trade keeps a persistent summary;
 *   - a trade opened from Trade History says it is today's view (N03), with
 *     no URL change (the share-link format is frozen);
 *   - a share link names what it could not restore (C04).
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import TradePackageBreakdown from "@/components/trade/TradePackageBreakdown";
import TradeDecisionReasoning, {
  DIMENSION_LABELS,
  coverageRows,
} from "@/components/trade/TradeDecisionReasoning";
import { TradeMeterMultiTeam } from "@/components/trade/TradeMeter";
import {
  INTEL_TABS,
  MultiTeamSummaryBar,
  TradeIntelTabs,
} from "@/app/trade/trade-layout";
import { multiTeamNetSummary } from "@/lib/trade-logic";
import { encodeTrade } from "@/lib/trade-share";
import { rememberHistoryOrigin } from "@/lib/trade-history-origin";
import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";
import ASSET_ONLY from "../fixtures/trade-war-room/asset-only.json";
import {
  COLD_LAZY_REVEAL,
  PREWARM_TIMEOUT_MS,
  prewarmTradeSections,
} from "../setup/trade-lazy-sections";

const row = (name, v, extra = {}) => ({
  name,
  pos: "WR",
  position: "WR",
  assetClass: "offense",
  rankDerivedValue: v,
  values: { full: v },
  ...extra,
});

// ── TradePackageBreakdown ────────────────────────────────────────────────

describe("TradePackageBreakdown", () => {
  const sides = [
    { id: 0, label: "A", assets: [row("Star", 6000, { age: 25, canonicalConsensusRank: 8 })] },
    {
      id: 1,
      label: "B",
      assets: [
        row("Depth One", 3000, { age: 23 }),
        row("Depth Two", 2500),
        { name: "Ghost", pos: "RB", assetClass: "offense", rankDerivedValue: null, values: {} },
      ],
    },
  ];
  const sideTotals = [
    { raw: 6000, adjustment: 700, adjusted: 6700 },
    { raw: 5500, adjustment: 0, adjusted: 5500 },
  ];

  it("draws one bar per side on one scale, VA as its own segment, every number in the legend", () => {
    render(<TradePackageBreakdown sides={sides} sideTotals={sideTotals} valueMode="full" />);
    const barA = screen.getByTestId("package-bar-A");
    const segsA = barA.querySelectorAll("[data-segment]");
    expect([...segsA].map((s) => s.getAttribute("data-segment"))).toEqual(["1", "va"]);
    // One scale: the largest drawn total (6,700) is 100%.
    expect(segsA[0].style.width).toBe(`${(6000 / 6700) * 100}%`);
    expect(within(barA).getByRole("img").getAttribute("aria-label")).toBe(
      "Side A: 1. Star 6,000, Value Adjustment 700; adjusted total 6,700",
    );
    // The unpriced piece is never drawn, and the legend says "not priced".
    const segsB = screen.getByTestId("package-bar-B").querySelectorAll("[data-segment]");
    expect(segsB).toHaveLength(2);
    expect(screen.getByText("not priced")).toBeInTheDocument();
    expect(screen.getByText("+700")).toBeInTheDocument();
  });

  it("states the facts per side without averaging a missing value as 0", () => {
    render(<TradePackageBreakdown sides={sides} sideTotals={sideTotals} valueMode="full" />);
    const table = screen.getByRole("table", { name: /Quick trade facts/ });
    const cells = (name) =>
      within(within(table).getByRole("row", { name: new RegExp(`^${name}`) }))
        .getAllByRole("cell")
        .map((c) => c.textContent);
    expect(cells("Pieces")).toEqual(["Pieces", "1", "3"]);
    expect(cells("Average piece value")).toEqual(["Average piece value", "6,000", "2,750 (2 of 3)"]);
    expect(cells("Average player age")).toEqual(["Average player age", "25.0", "23.0 (1 of 3)"]);
    expect(cells("Average consensus rank")).toEqual(["Average consensus rank", "8.0", "—"]);
    expect(cells("Largest piece's share")).toEqual(["Largest piece's share", "100%", "55%"]);
    expect(cells("Not priced")).toEqual(["Not priced", "none", "Ghost"]);
    // No better/worse reading of concentration.
    expect(screen.getByTestId("package-concentration-note").textContent).toMatch(
      /not better or worse on its own/,
    );
  });

  it("an empty trade gets a sentence, not empty bars", () => {
    render(
      <TradePackageBreakdown
        sides={[
          { id: 0, label: "A", assets: [] },
          { id: 1, label: "B", assets: [] },
        ]}
        sideTotals={[]}
        valueMode="full"
      />,
    );
    expect(screen.queryByTestId("package-breakdown")).toBeNull();
    expect(screen.getByText(/Add assets to see how each package is built/)).toBeInTheDocument();
  });
});

// ── TradeDecisionReasoning ───────────────────────────────────────────────

describe("TradeDecisionReasoning — the decision's own words", () => {
  it("renders what would change it and all ten coverage records verbatim", () => {
    const decision = CONSOLIDATION.analysis.decision;
    render(<TradeDecisionReasoning decision={decision} emptyText="x" />);
    expect(screen.getByTestId("decision-what-would-change").textContent).toContain(
      decision.whatWouldChange[0].text,
    );
    const table = screen.getByRole("table", { name: /Evidence coverage/ });
    const bodyRows = within(table).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(10);
    expect(bodyRows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(
      decision.coverage.map((c) => DIMENSION_LABELS[c.dimension]),
    );
  });

  it("a dimension Asset-Only did not evaluate says so, with the reason", () => {
    const rows = coverageRows(ASSET_ONLY.analysis.decision.coverage);
    const immediate = rows.find((r) => r.dimension === "Immediate improvement");
    expect(immediate.state).toBe("Not evaluated (Asset-Only)");
    expect(immediate.note).toBe("Not included in Asset-Only analysis");
    const opportunity = rows.find((r) => r.dimension === "Opportunity cost");
    expect(opportunity.state).toBe("Not evaluated");
    expect(opportunity.note).toBe("Not connected to the analysis yet");
  });

  it("an unknown code is shown, never dropped", () => {
    expect(coverageRows([{ dimension: "new_axis", state: "brand_new" }])[0]).toMatchObject({
      dimension: "new axis",
      state: "brand new",
    });
  });

  it("with no decision it states why", () => {
    render(<TradeDecisionReasoning decision={null} emptyText="Pick your team." />);
    expect(screen.getByTestId("decision-reasoning-empty")).toHaveTextContent("Pick your team.");
  });
});

// ── TradeIntelTabs ───────────────────────────────────────────────────────

describe("TradeIntelTabs — only the open tab is rendered", () => {
  it("never calls a closed tab's panel, and switches on click / arrow keys", async () => {
    const panels = Object.fromEntries(
      INTEL_TABS.map((t) => [t.id, vi.fn(() => <p>{`${t.label} panel`}</p>)]),
    );
    function Harness() {
      const [tab, setTab] = React.useState("value");
      return <TradeIntelTabs active={tab} onChange={setTab} panels={panels} />;
    }
    const React = await import("react");
    render(<Harness />);
    expect(screen.getByText("Value panel")).toBeInTheDocument();
    for (const t of INTEL_TABS.slice(1)) expect(panels[t.id]).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("tab", { name: "Market" }));
    expect(screen.getByText("Market panel")).toBeInTheDocument();
    expect(screen.queryByText("Value panel")).toBeNull();
    expect(panels.roster).not.toHaveBeenCalled();
    const panel = screen.getByRole("tabpanel");
    expect(panel.getAttribute("aria-labelledby")).toBe(
      screen.getByRole("tab", { name: "Market" }).id,
    );
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(screen.getByText("Reasoning panel")).toBeInTheDocument();
  });
});

// ── MultiTeamSummaryBar ──────────────────────────────────────────────────

describe("MultiTeamSummaryBar — the multi-team meter's own reading", () => {
  const sides = [
    { id: 0, label: "A", assets: [row("a", 5000)] },
    { id: 1, label: "B", assets: [row("b", 4000)] },
    { id: 2, label: "C", assets: [row("c", 3000)] },
  ];
  // Each side sends and receives one piece, so its package utilities are
  // those pieces' values (computeSideFlows stamps them; a flow without one is
  // refused, never read as base 0 -- which used to grade this 2,000 worst gap
  // FAIR).  Per-team rule: each team's base is the larger of the two.
  const flows = [
    { given: 5000, received: 3000, net: -2000, utility: 5000, receivedUtility: 3000 },
    { given: 4000, received: 5000, net: 1000, utility: 4000, receivedUtility: 5000 },
    { given: 3000, received: 4000, net: 1000, utility: 3000, receivedUtility: 4000 },
  ];

  it("shows each team's own gap and the band of the widest one the meter shows (preliminary)", () => {
    const summary = multiTeamNetSummary(flows);
    render(
      <MultiTeamSummaryBar sides={sides} summary={summary} evalState={{ state: "complete" }} />,
    );
    const bar = screen.getByTestId("trade-multi-summary");
    expect(bar.textContent).toMatch(/A −2,000/);
    expect(bar.textContent).toMatch(/B \+1,000/);
    // Per-team rule: A's own gap (-2,000 of a 5,000 package) is the widest.
    expect(summary.worstIndex).toBe(0);
    expect(bar.textContent).toContain(`Preliminary · ${summary.verdict.label} · widest gap Side A −2,000`);
    expect(bar.textContent).toMatch(/final result in the War Room/);
    expect(within(bar).getByRole("link").getAttribute("href")).toBe("#trade-result");
    // The meter renders the same label from the same helper.
    const { container } = render(
      <TradeMeterMultiTeam sides={sides} sideTotals={[]} flows={flows} />,
    );
    expect(container.querySelector(".trade-meter-verdict").textContent).toBe(summary.verdict.label);
    // 2,000 / 5,000 = 40%: LOPSIDED, not the FAIR a missing base used to give.
    expect(summary.verdict.level).toBe("lopsided");
  });

  it("an empty or incomplete trade states that, never a band", () => {
    const { rerender } = render(
      <MultiTeamSummaryBar sides={sides} summary={null} evalState={{ state: "empty" }} />,
    );
    expect(screen.getByTestId("trade-multi-summary").textContent).toMatch(/Add assets to compare/);
    rerender(
      <MultiTeamSummaryBar
        sides={sides}
        summary={null}
        evalState={{ state: "incomplete", unpriced: [{ name: "x" }] }}
      />,
    );
    expect(screen.getByTestId("trade-multi-summary").textContent).toMatch(
      /Incomplete — 1 unpriced, no verdict/,
    );
  });
});

// ── The real page ────────────────────────────────────────────────────────

const ROWS = [
  row("Bijan Robinson", 8000, { pos: "RB", position: "RB", playerId: "9509", rank: 1 }),
  row("Puka Nacua", 7000, { playerId: "9493", rank: 3 }),
  row("Garrett Wilson", 6000, { playerId: "9488", rank: 9 }),
];
const RAW = { currentDraftYear: 2026, sleeper: { teams: [] } };

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({ loading: false, error: null, rows: ROWS, rawData: RAW }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, setSettings: () => {}, update: () => {}, hydrated: true }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: null,
    setSelectedTeam: () => {},
    idpEnabled: true,
    leagueMismatch: false,
    selectedLeagueKey: "dynasty_main",
    loading: false,
  }),
}));

function setPhone(on) {
  window.matchMedia = vi.fn((query) => ({
    matches: on && /max-width/.test(query),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe("/trade, rendered (TC-D2)", () => {
  let TradePage;
  beforeAll(async () => {
    await prewarmTradeSections();
    ({ default: TradePage } = await import("@/app/trade/page"));
  }, PREWARM_TIMEOUT_MS);

  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.history.replaceState(null, "", "/trade");
    setPhone(false);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    delete window.matchMedia;
  });

  it("has no Market / My league control (TCM-D09)", async () => {
    render(<TradePage />);
    await screen.findByRole("heading", { name: "Trade War Room" }, COLD_LAZY_REVEAL);
    expect(screen.queryByRole("radiogroup", { name: "Value basis" })).toBeNull();
    expect(screen.queryByText("My league")).toBeNull();
  });

  it("keeps CSV / JSON / Copy KTC URL in the More group and Simulate impact out of the toolbar", async () => {
    render(<TradePage />);
    const builder = await screen.findByRole("region", { name: "Trade builder" });
    expect(within(builder).queryByRole("button", { name: "Download CSV" })).toBeNull();
    expect(within(builder).queryByRole("button", { name: /Simulate impact/ })).toBeNull();
    const more = within(builder).getByRole("button", { name: "More" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    const group = screen.getByRole("group", { name: "More trade actions" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Copy KTC URL",
      "Download CSV",
      "Download JSON",
    ]);
    // Nothing to export yet: each says so by being disabled.
    for (const b of within(group).getAllByRole("button")) expect(b).toBeDisabled();
    fireEvent.keyDown(group, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "More trade actions" })).toBeNull();
  });

  it("the Roster tab is the roster-consequence surface and says why it is empty", async () => {
    render(<TradePage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Roster" }));
    expect(screen.getByRole("tabpanel").textContent).toMatch(/Pick your team/);
    await userEvent.click(screen.getByRole("tab", { name: "Reasoning" }));
    expect(
      await screen.findByTestId("decision-reasoning-empty", {}, COLD_LAZY_REVEAL),
    ).toHaveTextContent(/Pick your team/);
  });

  it("phones add through one bottom sheet per side that stays open between adds", async () => {
    setPhone(true);
    render(<TradePage />);
    const add = await screen.findByRole("button", { name: "Add to Side A" });
    // No inline dropdown search on the phone layout.
    expect(screen.queryByLabelText("Search to add a player to Side A")).toBeNull();
    await userEvent.click(add);
    const sheet = await screen.findByRole("dialog", { name: "Add to Side A" }, COLD_LAZY_REVEAL);
    const input = within(sheet).getByLabelText("Search to add a player to Side A");
    await userEvent.type(input, "Bijan");
    await userEvent.click(within(sheet).getByRole("button", { name: /Bijan Robinson/ }));
    expect(within(sheet).getByRole("status").textContent).toMatch(/Added Bijan Robinson/);
    expect(input).toHaveValue("");
    // The sheet is still open for the next add; the asset is on Side A.
    await userEvent.click(within(sheet).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Remove Bijan Robinson from Side A" })).toBeTruthy();
  });

  it("a 3+-team trade keeps a persistent summary of the meter's reading", async () => {
    render(<TradePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add Team" }));
    const bar = await screen.findByTestId("trade-multi-summary");
    expect(bar.textContent).toMatch(/Add assets to compare/);
    expect(document.querySelectorAll(".trade-sticky-tray")).toHaveLength(1);
  });

  it("a trade opened from Trade History says it is today's view, not a replay (TCM-N03)", async () => {
    const share = encodeTrade({
      sides: [{ players: ["Bijan Robinson"] }, { players: ["Puka Nacua"] }],
    });
    // /trades records the hand-off on click; the URL itself is unchanged.
    rememberHistoryOrigin(share, "2025-10-03");
    window.history.replaceState(null, "", `/trade?share=${share}`);
    render(<TradePage />);
    const note = await screen.findByTestId("trade-history-origin");
    expect(note.textContent).toMatch(/made 2025-10-03/);
    expect(note.textContent).toMatch(/today.s board, rosters/);
    await userEvent.click(screen.getByRole("button", { name: "Clear Trade" }));
    expect(screen.queryByTestId("trade-history-origin")).toBeNull();
  });

  it("a share link with no Trade History hand-off shows no history banner", async () => {
    rememberHistoryOrigin("some-other-payload", "2025-10-03");
    const share = encodeTrade({ sides: [{ players: ["Bijan Robinson"] }, { players: [] }] });
    window.history.replaceState(null, "", `/trade?share=${share}`);
    render(<TradePage />);
    await screen.findByRole("button", { name: "Remove Bijan Robinson from Side A" });
    expect(screen.queryByTestId("trade-history-origin")).toBeNull();
  });

  it("names what a share link could not restore instead of dropping it silently (C04)", async () => {
    const share = encodeTrade({
      sides: [
        { players: ["Bijan Robinson"] },
        { players: ["Nobody On The Board", "Puka Nacua"] },
      ],
    });
    window.history.replaceState(null, "", `/trade?share=${share}`);
    render(<TradePage />);
    expect(
      await screen.findByRole("button", { name: "Remove Bijan Robinson from Side A" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Puka Nacua from Side B" })).toBeTruthy();
    expect(
      screen.getByText(/Not on today's board, so left out: Nobody On The Board\./),
    ).toBeInTheDocument();
  });
});

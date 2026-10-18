/**
 * TC-D (D1) — the /trade workspace layers.
 *
 * Pins, on the pieces and on the real page:
 *   - the five layers render in reading order (builder → result → decision →
 *     supporting intelligence → ideas & tools), each with its section-nav
 *     anchor, and every pre-existing section is still reachable;
 *   - Layer 2's package table is sideTotals verbatim (adjusted = raw + VA);
 *   - the decision echo is the War Room's OWN answer (reported through
 *     `onDecision`), verbatim, never a second verdict, and says why there is
 *     none in every non-answer state;
 *   - the verdict bar carries the decision word and links to the decision.
 */
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  DecisionSummary,
  ImmediateResultTable,
  TRADE_LAYERS,
  TradeSectionNav,
} from "@/app/trade/trade-layout";
import TradeWarRoom from "@/components/trade/TradeWarRoom";
import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";
import FORCED from "../fixtures/trade-war-room/forced-cut.json";
import {
  COLD_LAZY_REVEAL,
  PREWARM_TIMEOUT_MS,
  prewarmTradeSections,
} from "../setup/trade-lazy-sections";

const read = (rel) => fs.readFileSync(path.resolve(__dirname, "../..", rel), "utf8");

describe("TradeSectionNav", () => {
  it("links every layer in reading order with a real anchor", () => {
    render(<TradeSectionNav />);
    const nav = screen.getByRole("navigation", { name: "Trade sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "#trade-builder",
      "#trade-result",
      "#trade-decision",
      "#trade-intelligence",
      "#trade-tools",
    ]);
    expect(links.map((a) => a.textContent)).toEqual(TRADE_LAYERS.map((l) => l.label));
  });

  it("every nav target is 44 px tall on touch layouts", () => {
    const css = read("app/trade/trade.module.css");
    const rule = css.slice(css.indexOf(".sectionNavLink {"));
    expect(rule.slice(0, rule.indexOf("}"))).toMatch(/min-height:\s*44px/);
    const tray = css.slice(css.indexOf(".trayDecisionLink {"));
    expect(tray.slice(0, tray.indexOf("}"))).toMatch(/min-height:\s*44px/);
  });

  it("uses only the four canonical breakpoints", () => {
    const css = read("app/trade/trade.module.css");
    const tcd = css.slice(css.indexOf("TC-D workspace (D1)"));
    const widths = [...tcd.matchAll(/@media[^{]*?(\d+)px/g)].map((m) => Number(m[1]));
    expect(widths.length).toBeGreaterThan(0);
    for (const w of widths) expect([480, 768, 1024, 1320]).toContain(w);
  });
});

describe("ImmediateResultTable — sideTotals verbatim", () => {
  const sides = [{ label: "A" }, { label: "B" }];

  it("shows raw, Value Adjustment and adjusted per side", () => {
    render(
      <ImmediateResultTable
        sides={sides}
        sideTotals={[
          { raw: 6372.4, adjustment: 0, adjusted: 6372.4 },
          { raw: 1900.2, adjustment: 592.9, adjusted: 2493.1 },
        ]}
      />,
    );
    const table = within(screen.getByTestId("trade-immediate-result")).getByRole("table");
    const cells = (name) =>
      within(within(table).getByRole("row", { name: new RegExp(`^${name}`) }))
        .getAllByRole("cell")
        .map((c) => c.textContent);
    expect(cells("Raw")).toEqual(["Raw", "6,372", "1,900"]);
    // VA is the difference of the ROUNDED figures, so the parts add up; no VA
    // on a side reads as a dash, never as a fabricated "+0".
    expect(cells("Value Adjustment")).toEqual(["Value Adjustment", "—", "+593"]);
    expect(cells("Adjusted")).toEqual(["Adjusted", "6,372", "2,493"]);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Package",
      "Side A",
      "Side B",
    ]);
  });

  it("renders nothing rather than a 0 when a side has no totals", () => {
    const { container } = render(
      <ImmediateResultTable sides={sides} sideTotals={[{ raw: 1, adjustment: 0, adjusted: 1 }]} />,
    );
    expect(container.innerHTML).toBe("");
  });
});

describe("DecisionSummary — the War Room's answer, echoed", () => {
  const decision = CONSOLIDATION.analysis.decision;

  it("echoes the headline, confidence and primary reason verbatim", () => {
    render(<DecisionSummary summary={{ status: "ok", decision }} />);
    expect(screen.getByTestId("decision-summary-headline")).toHaveTextContent(
      decision.headlineText,
    );
    expect(screen.getByText(decision.confidence.statement)).toBeInTheDocument();
    expect(screen.getByText(decision.primaryReason.text)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Full analysis/ })).toHaveAttribute(
      "href",
      "#trade-decision",
    );
    // An echo, not the War Room: no second `decision-headline` test id.
    expect(screen.queryByTestId("decision-headline")).toBeNull();
  });

  it("keeps the previous answer dimmed and marked while it updates", () => {
    render(<DecisionSummary summary={{ status: "updating", decision }} />);
    expect(screen.getByTestId("decision-summary-headline")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/Updating/);
  });

  it.each([
    ["no-team", /Pick your team/],
    ["idle", /Add assets to both sides/],
    ["side-choice", /which side is yours/],
    ["loading", /Analyzing this trade/],
    ["error", /Analysis unavailable/],
    ["multi", /more than two teams/],
  ])("states why there is no decision (%s)", (status, words) => {
    render(<DecisionSummary summary={{ status, decision: null }} />);
    expect(screen.getByTestId("decision-summary")).toHaveTextContent(words);
    expect(screen.queryByTestId("decision-summary-headline")).toBeNull();
  });
});

describe("TradeWarRoom reports its decision through onDecision", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function settle() {
    await act(async () => {
      vi.advanceTimersByTime(800);
    });
    await act(async () => {});
  }

  it.each([
    ["consolidation", CONSOLIDATION],
    ["forced cut", FORCED],
  ])("the reported decision is the rendered payload's (%s)", async (_name, fixture) => {
    globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => fixture }));
    const onDecision = vi.fn();
    render(
      <TradeWarRoom
        request={{ ...fixture._fixture.request, mySide: 0 }}
        leagueKey="main"
        useTeamContext={fixture._fixture.request.useTeamContext}
        onDecision={onDecision}
      />,
    );
    expect(onDecision).toHaveBeenLastCalledWith({ status: "loading", decision: null });
    await settle();
    expect(onDecision).toHaveBeenLastCalledWith({
      status: "ok",
      decision: fixture.analysis.decision,
    });
    expect(screen.getByTestId("decision-headline")).toHaveTextContent(
      fixture.analysis.decision.headlineText,
    );
  });

  it("an incomplete trade reports why, never a decision", () => {
    const onDecision = vi.fn();
    const { rerender } = render(
      <TradeWarRoom request={null} teamName="" onDecision={onDecision} />,
    );
    expect(onDecision).toHaveBeenLastCalledWith({ status: "no-team", decision: null });
    rerender(<TradeWarRoom request={null} teamName="Jason" onDecision={onDecision} />);
    expect(onDecision).toHaveBeenLastCalledWith({ status: "idle", decision: null });
    rerender(
      <TradeWarRoom request={null} teamName="Jason" sideChoiceNeeded onDecision={onDecision} />,
    );
    expect(onDecision).toHaveBeenLastCalledWith({ status: "side-choice", decision: null });
  });
});

// ── The real page ────────────────────────────────────────────────────────

const ROWS = [
  {
    name: "Bijan Robinson",
    pos: "RB",
    position: "RB",
    assetClass: "offense",
    rankDerivedValue: 8000,
    values: { full: 8000 },
    rank: 1,
    blendedSourceRank: 1,
  },
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

describe("/trade lays the page out in five layers", () => {
  let TradePage;
  beforeAll(async () => {
    await prewarmTradeSections();
    ({ default: TradePage } = await import("@/app/trade/page"));
  }, PREWARM_TIMEOUT_MS);

  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builder → result → decision → intelligence → tools, every section kept", async () => {
    render(<TradePage />);
    await screen.findByRole("heading", { name: "Trade War Room" }, COLD_LAZY_REVEAL);
    await screen.findByRole("heading", { name: "Trade suggestions" }, COLD_LAZY_REVEAL);
    const ids = TRADE_LAYERS.map((l) => l.id);
    const nodes = ids.map((id) => document.getElementById(id));
    for (const [i, n] of nodes.entries()) expect(n, ids[i]).not.toBeNull();
    for (let i = 1; i < nodes.length; i += 1) {
      // DOCUMENT_POSITION_FOLLOWING: each layer comes after the previous one.
      expect(nodes[i - 1].compareDocumentPosition(nodes[i]) & 4).toBe(4);
    }
    const inLayer = (id) => within(document.getElementById(id));
    // Builder: controls and both side searches.
    expect(inLayer("trade-builder").getByRole("button", { name: "Clear Trade" })).toBeTruthy();
    expect(inLayer("trade-builder").getByLabelText("Search to add a player to Side B")).toBeTruthy();
    // Result: the meter's empty state (never a band on an empty trade).
    expect(inLayer("trade-result").getByText(/No verdict until there is a trade/)).toBeTruthy();
    // Decision: the War Room itself.
    expect(inLayer("trade-decision").getByRole("heading", { name: "Trade War Room" })).toBeTruthy();
    // Supporting intelligence: Second opinions + Recent real trades.
    expect(inLayer("trade-intelligence").getByText("Second opinions")).toBeTruthy();
    expect(inLayer("trade-intelligence").getByText("Recent real trades")).toBeTruthy();
    // Ideas & tools: the suggestions desk.
    expect(inLayer("trade-tools").getByRole("heading", { name: "Trade suggestions" })).toBeTruthy();
    // The desktop decision echo states why there is no decision yet.
    expect(screen.getByTestId("decision-summary")).toHaveTextContent(/Pick your team/);
  });
});

describe("/trade source pins (TC-D)", () => {
  const page = read("app/trade/page.jsx");

  it("loads the War Room only through a dynamic import, prefetched on mount", () => {
    expect(page).not.toMatch(/import\s+TradeWarRoom\s+from/);
    expect(page).toMatch(/import\(\s*"@\/components\/trade\/TradeWarRoom"\s*\)/);
    expect(page).toMatch(/const TradeWarRoom = dyn\(loadWarRoom/);
    expect(page).toMatch(/prefetch\(loadWarRoom\)/);
  });

  it("the simulation result no longer renders above the builder", () => {
    expect(page.indexOf("<SimulationPanel")).toBeGreaterThan(page.indexOf('id="trade-intelligence"'));
  });

  it("the suggestions rail no longer precedes the builder", () => {
    expect(page.indexOf("<ProactiveSuggestionsRail")).toBeGreaterThan(page.indexOf('id="trade-tools"'));
  });

  it("the verdict bar links to the decision and carries only the War Room's word", () => {
    const tray = page.slice(page.indexOf('className="trade-sticky-tray"'));
    expect(tray).toMatch(/href="#trade-decision"/);
    expect(page).toMatch(/decisionSummary\.decision\?\.headlineText/);
  });
});

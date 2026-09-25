/**
 * Player File (/players/[playerId]) — populated-state structure and
 * accessibility semantics, from a committed fixture.
 *
 * Before this file NOTHING rendered the Player File: no component test and
 * no Playwright spec. It is one of the two PSI reference routes
 * (docs/ui/UI_PARALLEL_LEDGER.md), so the populated state needs a
 * deterministic net that runs in the fast frontend suite, independent of
 * the e2e stack. The browser half — real axe, focus painting, viewport
 * overflow, reduced motion — lives in
 * tests/e2e/specs/psi-rankings-player-a11y.spec.js; this file pins the
 * DOM contract those scans stand on:
 *
 *   - exactly one <h1>, and it is the player's name;
 *   - a named tablist whose tabs and tabpanels are cross-wired
 *     (aria-controls ⇄ id, aria-labelledby ⇄ tab id), one tab stop;
 *   - Arrow/Home/End move selection AND focus (roving tabindex);
 *   - MISSING IS NEVER ZERO: an unpriced player reads "not priced", and
 *     an unranked one shows no rank tile rather than "#0";
 *   - the unresolved-link state stays inside the PSI scope with a way back.
 *
 * The page's section components are stubbed (they fetch); the compute*
 * helpers it shares with PlayerPopup run for real, so the numbers shown
 * are the page's actual derivation from the fixture row.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makePlayer } from "../fixtures/players";

let mockParams = { playerId: "4984" };
let mockApp = {};

vi.mock("next/navigation", () => ({
  useParams: () => mockParams,
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => mockApp,
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({ state: { watchlist: [] }, toggleWatchlist: vi.fn(), serverBacked: false }),
}));
// PlayerPopup's module-level hook imports — mocked so importing it for the
// shared helpers pulls in no network or context providers.
vi.mock("@/components/useTeam", () => ({ useTeam: () => ({ selectedTeam: null }) }));
vi.mock("@/components/useTerminal", () => ({ useTerminal: () => ({ signals: [] }) }));
vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeagueKey: "dynasty_main", loading: false }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ byPlayer: new Map(), digestByPlayer: new Map() }),
}));
vi.mock("@/components/PlayerRankHistoryChart", () => ({
  default: () => <div data-testid="rank-history-stub" />,
}));
vi.mock("@/components/PlayerPopup", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    RosContextSection: () => <div data-testid="ros-section-stub" />,
    PlayerContextSection: () => <div data-testid="context-section-stub" />,
    RealizedPointsSection: () => <div data-testid="realized-section-stub" />,
    IntelContextSection: () => <div data-testid="intel-section-stub" />,
    PlayerNewsSection: () => <div data-testid="news-section-stub" />,
  };
});

import PlayerFilePage from "@/app/players/[playerId]/page";

// Fixture: a priced, ranked QB with two value-based source contributions,
// plus a second QB so the position rank is a real ordinal.
const JOSH = makePlayer({
  name: "Josh Allen",
  rank: 1,
  canonicalConsensusRank: 1,
  rankDerivedValue: 9200,
  values: { full: 9200 },
  siteCount: 2,
  confidenceLabel: "High",
  canonicalTierId: 1,
  age: 30,
  yearsExp: 8,
  canonicalSites: { ktcSfTep: 9300, idpTradeCalc: 9100 },
  sourceRankMeta: {
    ktcSfTep: { valueContribution: 9300 },
    idpTradeCalc: { valueContribution: 9100 },
  },
  raw: { playerId: "4984", team: "BUF" },
});
const LAMAR = makePlayer({
  name: "Lamar Jackson",
  rank: 2,
  canonicalConsensusRank: 2,
  rankDerivedValue: 8900,
  values: { full: 8900 },
  raw: { playerId: "4881", team: "BAL" },
});

function populated(rows = [JOSH, LAMAR]) {
  return {
    rows,
    rawData: { sleeper: { teams: [] } },
    loading: false,
    error: "",
    failure: null,
    retry: vi.fn(),
  };
}

/** The value a StatTile shows beside `label` (null when the tile is absent). */
function tileValue(label) {
  const labelEl = screen.queryByText(label, { selector: ".ds-stat__label" });
  if (!labelEl) return null;
  return labelEl.parentElement.querySelector(".ds-stat__value").textContent;
}

beforeEach(() => {
  mockParams = { playerId: "4984" };
  mockApp = populated();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
});

describe("Player File — populated state", () => {
  it("renders one <h1> naming the player, inside the PSI editorial scope", () => {
    const { container } = render(<PlayerFilePage />);
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("Josh Allen");
    expect(container.querySelector("section.psi-editorial")).not.toBeNull();
  });

  it("shows the backend value, rank and position rank as stat tiles", () => {
    render(<PlayerFilePage />);
    expect(tileValue("Our Value")).toBe((9200).toLocaleString());
    expect(tileValue("Overall rank")).toBe("#1");
    expect(tileValue("Position rank")).toBe("QB1");
    expect(tileValue("Confidence")).toBe("High");
    expect(screen.queryByText("not priced")).toBeNull();
  });

  it("wires a named tablist to its panels with one tab stop", () => {
    render(<PlayerFilePage />);
    const tablist = screen.getByRole("tablist", { name: "Player sections" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      "Overview",
      "Market",
      "Trades",
      "Performance",
      "Intel",
    ]);
    expect(tabs.filter((t) => t.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    for (const tab of tabs) {
      const panel = document.getElementById(tab.getAttribute("aria-controls"));
      expect(panel, `${tab.textContent} must control a real panel`).not.toBeNull();
      expect(panel).toHaveAttribute("role", "tabpanel");
      expect(panel).toHaveAttribute("aria-labelledby", tab.id);
      // Only the selected panel is exposed; the rest are hidden, not just empty.
      if (tab.getAttribute("aria-selected") === "true") {
        expect(panel).not.toHaveAttribute("hidden");
      } else {
        expect(panel).toHaveAttribute("hidden");
      }
    }
  });

  it("moves selection and focus with Arrow/Home/End (roving tabindex)", async () => {
    const user = userEvent.setup();
    render(<PlayerFilePage />);
    const tab = (name) => screen.getByRole("tab", { name });
    tab("Overview").focus();

    await user.keyboard("{ArrowRight}");
    expect(tab("Market")).toHaveFocus();
    expect(tab("Market")).toHaveAttribute("aria-selected", "true");
    expect(tab("Market")).toHaveAttribute("tabindex", "0");
    expect(tab("Overview")).toHaveAttribute("tabindex", "-1");
    // The Market panel now shows the per-source breakdown from the fixture.
    const market = screen.getByRole("tabpanel", { name: "Market" });
    expect(within(market).getByText((9300).toLocaleString())).toBeInTheDocument();

    await user.keyboard("{End}");
    expect(tab("Intel")).toHaveFocus();
    expect(screen.getByTestId("intel-section-stub")).toBeInTheDocument();

    await user.keyboard("{Home}");
    expect(tab("Overview")).toHaveFocus();

    await user.keyboard("{ArrowLeft}");
    expect(tab("Intel")).toHaveFocus();
  });

  it("exposes the watchlist control as a toggle button", () => {
    render(<PlayerFilePage />);
    expect(screen.getByRole("button", { name: /Watch/ })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("Player File — missing / unresolved states", () => {
  it("an unpriced, unranked player reads 'not priced' — never 0 or #0", () => {
    const unpriced = makePlayer({
      name: "Deep Stash",
      rank: undefined,
      canonicalConsensusRank: null,
      rankDerivedValue: null,
      values: {},
      siteCount: 0,
      raw: { playerId: "9999", team: "FA" },
    });
    mockParams = { playerId: "9999" };
    mockApp = populated([JOSH, unpriced]);
    render(<PlayerFilePage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Deep Stash");
    expect(tileValue("Our Value")).toBe("not priced");
    expect(tileValue("Overall rank")).toBeNull();
    expect(tileValue("Position rank")).toBeNull();
    expect(screen.queryByText("#0")).toBeNull();
  });

  it("an unresolvable link renders an honest not-found state with a way back", () => {
    mockParams = { playerId: "no-such-player" };
    const { container } = render(<PlayerFilePage />);
    expect(screen.getByText("Player not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Rankings" })).toHaveAttribute("href", "/rankings");
    expect(container.querySelector("section.psi-editorial")).not.toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
  });
});

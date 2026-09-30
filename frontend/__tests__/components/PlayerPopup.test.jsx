// PlayerPopup behavioral tests.
//
// PlayerPopup is wired through five context hooks + a network-fetching
// child chart. We mock the hooks to controlled defaults and stub the
// chart so the test exercises PlayerPopup's own behavior (render,
// close affordances, add-to-trade) and nothing downstream.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { makePlayer } from "../fixtures/players";

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: {} }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: null }),
}));
vi.mock("@/components/useTerminal", () => ({
  useTerminal: () => ({ signals: [] }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: {},
    toggleWatchlist: vi.fn(),
    serverBacked: false,
  }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {} }),
}));
// League context for the Sharp Tracker intel section — a stable key
// keeps the intel fetch deterministic in these tests.
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeagueKey: "dynasty_main", loading: false }),
}));
// Child chart fetches /api/data/player-source-history — stub it out.
vi.mock("@/components/PlayerRankHistoryChart", () => ({
  default: () => <div data-testid="rank-history-stub" />,
}));
// next/link needs the Next runtime; a plain anchor is enough here — but
// it must forward the rest of its props, or aria-labels set on a linked
// control silently vanish and the test asserts against a name the real
// component does not have.
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import PlayerPopup, { computeSiteDetails, computeValueChain } from "@/components/PlayerPopup";
import { getSiteKeys } from "@/lib/dynasty-data";

beforeEach(() => {
  // PlayerPopup loads ROS values via fetch in an effect.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
  );
});

function renderPopup(extra = {}) {
  const onClose = vi.fn();
  const onAddToTrade = vi.fn();
  const row = makePlayer();
  render(
    <PlayerPopup
      row={row}
      siteKeys={["ktc", "fantasycalc"]}
      onClose={onClose}
      onAddToTrade={onAddToTrade}
      {...extra}
    />,
  );
  return { onClose, onAddToTrade, row };
}

describe("PlayerPopup", () => {
  it("renders the player and a close control", () => {
    const { row } = renderPopup();
    expect(screen.getAllByText(new RegExp(row.name, "i")).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: /close player details/i }),
    ).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const { onClose } = renderPopup();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when the close button is clicked", () => {
    const { onClose } = renderPopup();
    fireEvent.click(
      screen.getByRole("button", { name: /close player details/i }),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("adds to trade then closes", () => {
    const { onClose, onAddToTrade, row } = renderPopup();
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`add ${row.name} to trade`, "i") }),
    );
    expect(onAddToTrade).toHaveBeenCalledWith(row);
    expect(onClose).toHaveBeenCalled();
  });

  // /players/compare is URL-driven but nothing in the product linked to
  // it — it was a command-palette-only destination, so the only way to
  // reach it was to already know it existed.  The popup is where a user
  // is looking at one player and wondering how he stacks up.
  it("offers a Compare link seeded with this player", () => {
    const { row } = renderPopup();
    const link = screen.getByRole("link", {
      name: new RegExp(`compare ${row.name}`, "i"),
    });
    expect(link).toHaveAttribute(
      "href",
      `/players/compare?p1=${encodeURIComponent(row.name)}`,
    );
  });

  it("closes the popup when Compare is followed", () => {
    // Otherwise the overlay stays mounted over the page just navigated to.
    const { onClose } = renderPopup();
    fireEvent.click(screen.getByRole("link", { name: /compare/i }));
    expect(onClose).toHaveBeenCalled();
  });
});


describe("compact source inventory", () => {
  it("preserves explicit source order for tied contributions including unknown sources", () => {
    const row = { sourceRankMeta: {
      ktcTradesSfTep: { valueContribution: 9999 },
      unknownSource: { valueContribution: 9999 },
      idpTradeCalc: { valueContribution: 9999 },
    } };
    const contract = { sites: [
      { key: "idpTradeCalc" }, { key: "unknownSource" }, { key: "ktcTradesSfTep" },
    ] };
    const details = computeSiteDetails(row, getSiteKeys(contract));
    expect(details.map(({ key }) => key)).toEqual([
      "idpTradeCalc", "unknownSource", "ktcTradesSfTep",
    ]);
    expect(details.map(({ value, pct }) => [value, pct])).toEqual([
      [9999, 100], [9999, 100], [9999, 100],
    ]);
    expect(details.find(({ key }) => key === "unknownSource").label).toBe("unknownSource");
    expect(computeSiteDetails(row, getSiteKeys({}))).not.toEqual(details);
  });

  // 2026-09-29: the breakdown listed ktcSfTep (a historical non-voting
  // fallback) and ktcCrowdTradesSfTep (the KTC Market BENCHMARK) under
  // raw keys, beside the real KTC Crowd / Trades inputs — measured on
  // Josh Allen's live row.
  it("lists only sources that voted — never the KTC Market benchmark or KTC fallbacks", () => {
    const row = {
      sourceRankMeta: {
        ktcCrowdSfTep: { valueContribution: 9997 },
        ktcTradesSfTep: { valueContribution: 9999 },
      },
      canonicalSites: { ktcSfTep: 9997, ktc: 9990 },
      rawSourceValues: { ktcSfTep: 9997, ktcCrowdTradesSfTep: 9645 },
    };
    const keys = computeSiteDetails(row).map(({ key }) => key);
    expect(keys).toEqual(expect.arrayContaining(["ktcCrowdSfTep", "ktcTradesSfTep"]));
    expect(keys).not.toContain("ktcSfTep");
    expect(keys).not.toContain("ktcCrowdTradesSfTep");
    expect(keys).not.toContain("ktc");
  });

  it("leaves out observations that did not vote on this row (stale / unhealthy, Hampel-dropped)", () => {
    const row = {
      sourceRankMeta: {
        idpTradeCalc: { valueContribution: 5405, appliedWeight: 1 },
        dlfIdp: { valueContribution: 3721, appliedWeight: 0, contributedToBlend: false, excludedReason: "freshness_or_health_zero_weight" },
        draftSharksIdp: { valueContribution: 1950, appliedWeight: 1, hampelDropped: true },
      },
    };
    expect(computeSiteDetails(row).map(({ key }) => key)).toEqual(["idpTradeCalc"]);
  });
});

// The Player File and the popup both title this "how we arrived at Our
// Value", so the chain must END on the published value.
describe("value chain truthfulness", () => {
  it("an offense row (flat blend, α = 0) is one Blended value stage equal to the published value", () => {
    // Josh Allen, live 2026-09-29: anchorValue 9989 is a diagnostic stamp
    // on offense rows; the old chain presented it as the derivation.
    const chain = computeValueChain({
      assetClass: "offense",
      rankDerivedValue: 9978,
      anchorValue: 9989,
      subgroupBlendValue: 9976,
      subgroupDelta: -13,
      alphaShrinkage: 0,
    });
    expect(chain).toHaveLength(1);
    expect(chain[0].label).toBe("Blended value");
    expect(chain[0].value).toBe(9978);
    expect(chain.some((s) => /IDPTC|Anchor/.test(`${s.label} ${s.description}`))).toBe(false);
  });

  it("a single-source offense row states the single-source rule and still ends on its value", () => {
    const chain = computeValueChain({
      assetClass: "offense",
      rankDerivedValue: 672,
      anchorValue: 2242,
      alphaShrinkage: 0,
      isSingleSource: true,
    });
    expect(chain.map((s) => s.value)).toEqual([672]);
    expect(chain[0].description).toMatch(/30%/);
  });

  it("an IDP row keeps the anchor + α-shrunk subgroup stages and ends on its value", () => {
    // Myles Garrett, live 2026-09-29.
    const chain = computeValueChain({
      assetClass: "idp",
      rankDerivedValue: 5223,
      anchorValue: 5331,
      subgroupBlendValue: 4252,
      subgroupDelta: -1079,
      alphaShrinkage: 0.1,
    });
    expect(chain.map((s) => s.key)).toEqual(["anchor", "subgroup"]);
    expect(chain[chain.length - 1].value).toBe(5223);
  });

  it("reconciles a later board pass with a Published value stage instead of stopping short", () => {
    // e.g. a pick tethered to the rookie at its slot after the blend.
    const chain = computeValueChain({
      assetClass: "pick",
      rankDerivedValue: 4100,
      anchorValue: 3900,
      alphaShrinkage: 0.1,
    });
    const last = chain[chain.length - 1];
    expect(last.key).toBe("published");
    expect(last.value).toBe(4100);
    expect(last.delta).toBe(200);
  });

  it("a derived pick says what it was derived from instead of describing a blend", () => {
    const chain = computeValueChain({
      assetClass: "pick",
      rankDerivedValue: 1835,
      alphaShrinkage: null,
      raw: { pickValueProvenance: { class: "derived_round_step", basis: "2027 Early 4th" } },
    });
    expect(chain).toHaveLength(1);
    expect(chain[0].label).toBe("Derived value");
    expect(chain[0].description).toMatch(/2027 Early 4th/);
    expect(chain[0].value).toBe(1835);
  });

  it("a tethered slot pick's reconcile stage names the rookie it was priced from", () => {
    const chain = computeValueChain({
      assetClass: "pick",
      rankDerivedValue: 7793,
      anchorValue: 8015,
      alphaShrinkage: 0.1,
      raw: { pickValueProvenance: { class: "rookie_pool_tether", basis: "Jeremiyah Love" } },
    });
    const last = chain[chain.length - 1];
    expect(last.key).toBe("published");
    expect(last.description).toMatch(/Jeremiyah Love/);
  });

  it("an unpriced row has no chain rather than a chain ending on 0", () => {
    expect(computeValueChain({ assetClass: "offense", rankDerivedValue: null, alphaShrinkage: 0 })).toEqual([]);
  });
});

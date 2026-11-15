// TC-B / TCM-A02, A03, B04 — display-only builder facts: the per-side
// position mix, a player's age, and the derived-pick (PRIOR) disclosure.
import { describe, expect, it } from "vitest";
import { formatAssetAge, packageComposition, packageCompositionText } from "@/lib/trade-assets";
import { derivedPickDisclosure } from "@/lib/pick-provenance";
import { DERIVED_PICK_DESCRIPTIONS } from "@/lib/pick-provenance-text";

const row = (name, pos, extra = {}) => ({ name, pos, assetClass: pos === "PICK" ? "pick" : "offense", ...extra });

describe("packageComposition", () => {
  it("counts every copy in football order, picks last", () => {
    const assets = [row("a", "WR"), row("b", "QB"), row("a", "WR"), row("p", "PICK"), row("p", "PICK"), row("l", "LB")];
    expect(packageComposition(assets)).toEqual([
      { label: "QB", count: 1 },
      { label: "WR", count: 2 },
      { label: "LB", count: 1 },
      { label: "Pick", count: 2 },
    ]);
    expect(packageCompositionText(assets)).toBe("1 QB · 2 WR · 1 LB · 2 Picks");
  });

  it("counts a position-less row as unknown instead of dropping it", () => {
    expect(packageCompositionText([row("x", "?")])).toBe("1 Unknown position");
    expect(packageCompositionText([])).toBe("");
  });
});

describe("formatAssetAge", () => {
  it("shows a real age and never 0 for a missing one", () => {
    expect(formatAssetAge(row("a", "WR", { age: 24 }))).toBe("Age 24");
    expect(formatAssetAge(row("a", "WR", { age: 24.63 }))).toBe("Age 24.6");
    expect(formatAssetAge(row("a", "WR", { age: null }))).toBeNull();
    expect(formatAssetAge(row("a", "WR", { age: 0 }))).toBeNull();
    expect(formatAssetAge(row("p", "PICK", { age: 3 }))).toBeNull();
  });
});

describe("derivedPickDisclosure", () => {
  it("names the generic grade's tier-average prior with its basis", () => {
    const generic = row("2027 Round 1", "PICK", {
      raw: {
        pickValueProvenance: {
          class: "derived_uniform_tier_ev",
          classification: "PRIOR",
          basis: ["2027 Early 1st", "2027 Mid 1st", "2027 Late 1st"],
        },
      },
    });
    expect(derivedPickDisclosure(generic)).toEqual({
      cls: "derived_uniform_tier_ev",
      label: "Generic: tier average",
      basis: "2027 Early 1st, 2027 Mid 1st, 2027 Late 1st",
      isPrior: true,
    });
    // Every class the builder labels has the Player popup's sentence too.
    expect(Object.keys(DERIVED_PICK_DESCRIPTIONS).sort()).toEqual([
      "derived_round_step",
      "derived_uniform_tier_ev",
      "derived_year_step",
    ]);
    for (const cls of Object.keys(DERIVED_PICK_DESCRIPTIONS)) {
      expect(DERIVED_PICK_DESCRIPTIONS[cls]).toBeTruthy();
      expect(derivedPickDisclosure({ raw: { pickValueProvenance: { class: cls } } }).cls).toBe(cls);
    }
  });

  it("discloses nothing for a market-priced or tethered pick", () => {
    const market = row("2027 Mid 1st", "PICK", { raw: { pickValueProvenance: { class: "direct_market_blend" } } });
    const tether = row("2026 Pick 1.04", "PICK", { raw: { pickValueProvenance: { class: "rookie_pool_tether" } } });
    expect(derivedPickDisclosure(market)).toBeNull();
    expect(derivedPickDisclosure(tether)).toBeNull();
    expect(derivedPickDisclosure(row("x", "WR"))).toBeNull();
  });
});

/**
 * V1-131 / audit F-25 — the nav must not OFFER a page whose endpoints
 * all 503.
 *
 * THE DEFECT, measured on `main` @ 131abf9f9 before this fix:
 * `src/api/feature_flags.py` defaults `consensus_edge: False` (ADR-023 —
 * the measured edge did not survive re-analysis), every board handler in
 * `src/consensus_edge/api.py` answers `503 feature_disabled` while it is
 * off, and `nav-model.js` offered `/consensus-edge` unconditionally. So
 * the DEFAULT production state was a menu entry to a dead page.
 *
 * One correction to the row's wording, made by measurement rather than
 * assumed: it says "its three endpoints 503". `/players`, `/top`,
 * `/player/{key}` and `/health` do. `/methodology` deliberately does
 * NOT — it answers 200 even with the flag off and stamps
 * `"enabled": false`, precisely so a user can read what the feature
 * claims without being able to see a board. The row's REQUIREMENT is
 * unaffected (the page itself is unusable), and that endpoint is what
 * makes an honest capability signal possible at all.
 *
 * WHY THIS IS A MODEL-LEVEL TEST, NOT A COMPONENT ONE.
 * `NAV_MODEL` feeds five independent offer surfaces — the desktop
 * TopBar, the mobile drawer, the command palette, the `/more` site map,
 * and (unfiltered, correctly) `pageTitleFor`. Asserting on one component
 * would let the other four keep offering the dead page: hide it from the
 * drawer and ⌘K still routes there. So this pins the invariant on every
 * derivation at once, and derives the gated set FROM THE MODEL so a
 * future capability-gated item is covered without editing this file.
 */
import { describe, expect, it } from "vitest";
import {
  NAV_MODEL,
  SYSTEM_MODEL,
  flattenNav,
  itemIsOffered,
  navGroupsFor,
  paletteTargets,
  pageTitleFor,
} from "@/lib/nav-model";

/**
 * The destination this row is about, named explicitly.
 *
 * Deliberately NOT derived from the model. The derived set below is what
 * makes a future gated item covered for free, but derivation alone is a
 * weak detector for THIS defect: deleting the `capability` key — the
 * literal pre-fix state — empties the derived set and turns every
 * derived assertion vacuously green. Naming the route pins the actual
 * regression, so reverting the fix fails these tests broadly rather than
 * on one guard.
 */
const CONSENSUS_EDGE = "/consensus-edge";

/** Every item in the shipped model that declares a capability. */
const GATED = flattenNav(NAV_MODEL).filter((i) => i.capability);

/** The gated hrefs we assert on: the derived set plus the named route. */
const MUST_BE_GATED = [...new Set([...GATED.map((i) => i.href), CONSENSUS_EDGE])];

/** Capability map with every declared capability switched ON. */
const ALL_ON = Object.fromEntries(GATED.map((i) => [i.capability, true]));

/** The states that must all mean "do not offer". */
const NOT_OFFERED_STATES = [
  ["undefined — probe has not answered", undefined],
  ["null — probe failed", null],
  ["empty map — backend sent no features block", {}],
  ["explicitly false — flag is off", Object.fromEntries(GATED.map((i) => [i.capability, false]))],
  // A truthy-but-not-true value must not pass either: the server sends
  // booleans, so anything else is a shape we did not agree to.
  ["truthy non-boolean", Object.fromEntries(GATED.map((i) => [i.capability, "yes"]))],
];

/** Every href any offer surface would show for a given capability map. */
function offeredHrefs(capabilities) {
  const groups = navGroupsFor({ capabilities });
  return new Set([
    ...flattenNav(groups).map((i) => i.href),
    ...groups.map((g) => g.href),
    ...paletteTargets({ capabilities }).map((t) => t.href),
    // /more renders exactly this composition.
    ...flattenNav([...groups, SYSTEM_MODEL]).map((i) => i.href),
  ]);
}

describe("V1-131 — capability-gated nav destinations", () => {
  it("the model actually declares a gated destination (guards against a vacuous suite)", () => {
    // If Consensus Edge is ever retired outright this fails loudly
    // rather than passing over an empty set — which is how a gating
    // test quietly stops testing anything.
    expect(GATED.length).toBeGreaterThan(0);
    expect(GATED.map((i) => i.href)).toContain(CONSENSUS_EDGE);
  });

  for (const [label, capabilities] of NOT_OFFERED_STATES) {
    it(`offers nothing gated when capabilities are ${label}`, () => {
      const offered = offeredHrefs(capabilities);
      for (const href of MUST_BE_GATED) {
        expect(offered.has(href)).toBe(false);
      }
    });
  }

  it("offers the gated destination once the capability is explicitly true", () => {
    const offered = offeredHrefs({ ...ALL_ON, consensusEdge: true });
    for (const href of MUST_BE_GATED) {
      expect(offered.has(href)).toBe(true);
    }
  });

  it("gating removes ONLY the gated items — every other destination is untouched", () => {
    const ungated = flattenNav(NAV_MODEL)
      .filter((i) => !i.capability)
      .map((i) => i.href);
    const offered = offeredHrefs(null);
    for (const href of ungated) {
      expect(offered.has(href)).toBe(true);
    }
  });

  it("a group never advertises an href it is no longer offering", () => {
    // The clickable group label navigates to `group.href`. If that href
    // was the gated item, the label itself becomes the dead link — the
    // same defect wearing a different hat.
    for (const group of navGroupsFor({ capabilities: null })) {
      if (!group.items || !group.items.length) continue;
      expect(group.items.some((i) => i.href === group.href)).toBe(true);
    }
  });

  it("a group whose items are ALL gated away disappears rather than rendering empty", () => {
    const model = navGroupsFor({ capabilities: null });
    for (const group of model) {
      if (group.items) expect(group.items.length).toBeGreaterThan(0);
    }
  });

  it("gates the OFFER, never the ROUTE — a gated page can still name itself", () => {
    // /consensus-edge stays reachable by URL so an operator running with
    // RISKIT_FEATURE_CONSENSUS_EDGE=1 keeps their evaluation path. A
    // page you can reach must still render a real <h1>; titling it
    // "Chase Upside" would be a blank header for exactly that operator.
    for (const item of GATED) {
      expect(pageTitleFor(item.href)).toBe(item.label);
    }
  });

  it("itemIsOffered treats an item with no capability as always offerable", () => {
    expect(itemIsOffered({ href: "/rankings" }, null)).toBe(true);
    expect(itemIsOffered({ href: "/rankings" }, {})).toBe(true);
  });
});

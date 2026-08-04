/**
 * `IDP_CONSENSUS_KEYS` must not drift from the source registry.
 *
 * WHY THIS EXISTS
 * ===============
 * `display-helpers.js` hand-maintains a Set of the IDP sources that
 * make up the "expert consensus" side of the IDP Buy/Sell signal. A
 * hand-maintained mirror of a registry is the same shape as the
 * `value-history.js` curve constants and the `/rankings` Hill formula —
 * both of which drifted and both of which this audit already fixed.
 *
 * This one had drifted in BOTH directions at once:
 *
 *   - it OMITTED `dlfRookieIdp`, a real `overall_idp` source. 29 rows
 *     carry a rank from it and 28 of those shift their consensus mean
 *     by >= 1 rank once it is counted — a quietly biased mean, not a
 *     missing signal, which is why nothing looked broken.
 *   - its comment NAMED "FootballGuys IDP", which is not a key in
 *     either registry.
 *
 * WHAT THIS ASSERTS
 * =================
 * The set equals every `overall_idp` source in `RANKING_SOURCES`,
 * minus the retail anchor (`idpTradeCalc`) which is deliberately the
 * OTHER side of the comparison. Derived from the registry rather than
 * pinned as a literal, so adding a genuine IDP source updates the
 * expectation automatically and only a real divergence fails.
 *
 * `RANKING_SOURCES` is itself kept in lockstep with the Python
 * `_RANKING_SOURCES` by `tests/api/test_source_registry_parity.py`, so
 * this transitively pins against the backend registry too.
 */

import { describe, it, expect } from "vitest";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import { __testables } from "@/lib/display-helpers";

const { IDP_CONSENSUS_KEYS, IDP_RETAIL_KEY } = __testables;

describe("IDP_CONSENSUS_KEYS parity with the source registry", () => {
  const idpSources = RANKING_SOURCES.filter((s) => s.scope === "overall_idp").map(
    (s) => s.key,
  );

  it("the registry actually has overall_idp sources (non-vacuity)", () => {
    // Without this, every assertion below would pass against an empty
    // set if the scope tag were ever renamed.
    expect(idpSources.length).toBeGreaterThan(2);
    expect(idpSources).toContain(IDP_RETAIL_KEY);
  });

  it("contains every overall_idp source except the retail anchor", () => {
    const expected = new Set(idpSources.filter((k) => k !== IDP_RETAIL_KEY));
    const actual = new Set(IDP_CONSENSUS_KEYS);

    const missing = [...expected].filter((k) => !actual.has(k));
    const extra = [...actual].filter((k) => !expected.has(k));

    expect({ missing, extra }).toEqual({ missing: [], extra: [] });
  });

  it("does not contain the retail anchor — it is the other side of the comparison", () => {
    expect(IDP_CONSENSUS_KEYS.has(IDP_RETAIL_KEY)).toBe(false);
  });

  it("includes dlfRookieIdp, the source that was silently omitted", () => {
    // Named explicitly: this is the regression that motivated the test,
    // and a generic set-equality failure message would not say so.
    expect(IDP_CONSENSUS_KEYS.has("dlfRookieIdp")).toBe(true);
  });
});

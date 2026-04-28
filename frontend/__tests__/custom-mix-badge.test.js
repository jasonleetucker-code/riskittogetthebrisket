/**
 * Unit tests for the Custom Mix badge on the rankings page.
 *
 * The badge renders from ``describeCustomMix(rankingsOverride)`` which
 * is a pure function factored out of the React component so unit
 * tests can pin the business rules without a DOM environment.  The
 * component itself is a thin wrapper that reads the describe result
 * and renders a button + popover.
 *
 * Test matrix:
 *   1. Null / default rankingsOverride produces ``active: false`` so
 *      the badge is not rendered.
 *   2. ``isCustomized: true`` with a disabled source populates the
 *      disabled list and summary string.
 *   3. ``isCustomized: true`` with a non-default weight populates the
 *      reweighted list and summary string.
 *   4. Both disabled + reweighted in one map produces both lists.
 *   5. The summary format is "(N disabled, M reweighted)".
 *   6. Weight override matching the default is NOT reported as
 *      customized (the backend ``_summarize_source_overrides`` is
 *      the authority, so the frontend helper trusts its
 *      ``isCustomized`` flag).
 */
import { describe, expect, it } from "vitest";
import { describeCustomMix } from "@/app/rankings/page";

describe("describeCustomMix", () => {
  it("returns active:false for null / undefined / empty override block", () => {
    expect(describeCustomMix(null)).toEqual({
      active: false,
      disabled: [],
      reweighted: [],
      summary: "",
    });
    expect(describeCustomMix(undefined)).toEqual({
      active: false,
      disabled: [],
      reweighted: [],
      summary: "",
    });
    expect(describeCustomMix({})).toEqual({
      active: false,
      disabled: [],
      reweighted: [],
      summary: "",
    });
  });

  it("returns active:false when isCustomized is false", () => {
    const rankingsOverride = {
      isCustomized: false,
      enabledSources: ["ktcSfTep", "idpTradeCalc", "dlfSf"],
      weights: { ktcSfTep: 1.0, dlfSf: 1.0 },
      defaults: { ktcSfTep: 1.0, dlfSf: 1.0 },
      received: {},
    };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(false);
    expect(result.disabled).toEqual([]);
    expect(result.reweighted).toEqual([]);
    expect(result.summary).toBe("");
  });

  it("populates disabled list when a source is excluded", () => {
    const rankingsOverride = {
      isCustomized: true,
      enabledSources: ["idpTradeCalc", "dlfSf", "dynastyNerdsSfTep", "fantasyProsIdp", "dlfIdp"],
      weights: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      defaults: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      received: { ktcSfTep: { include: false } },
    };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(true);
    expect(result.disabled).toEqual(["KTC TE+"]);
    expect(result.reweighted).toEqual([]);
    expect(result.summary).toBe("(1 disabled)");
  });

  it("populates reweighted list for a non-default weight", () => {
    const rankingsOverride = {
      isCustomized: true,
      enabledSources: ["ktcSfTep", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep", "fantasyProsIdp", "dlfIdp"],
      weights: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 0.5, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      defaults: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      received: { dlfSf: { weight: 0.5 } },
    };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(true);
    expect(result.disabled).toEqual([]);
    expect(result.reweighted).toEqual(["DLF SF 1.0→0.5"]);
    expect(result.summary).toBe("(1 reweighted)");
  });

  it("reports both disabled and reweighted in the summary string", () => {
    const rankingsOverride = {
      isCustomized: true,
      enabledSources: ["idpTradeCalc", "dlfSf", "dynastyNerdsSfTep", "fantasyProsIdp", "dlfIdp"],
      weights: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 2.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      defaults: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      received: {
        ktcSfTep: { include: false },
        dlfSf: { weight: 2.0 },
      },
    };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(true);
    expect(result.disabled).toEqual(["KTC TE+"]);
    expect(result.reweighted).toEqual(["DLF SF 1.0→2.0"]);
    expect(result.summary).toBe("(1 disabled, 1 reweighted)");
  });

  it("lists multiple disabled sources", () => {
    const rankingsOverride = {
      isCustomized: true,
      enabledSources: ["dlfSf", "dynastyNerdsSfTep"],
      weights: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      defaults: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      received: {
        ktcSfTep: { include: false },
        idpTradeCalc: { include: false },
        fantasyProsIdp: { include: false },
        dlfIdp: { include: false },
      },
    };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(true);
    expect(result.disabled).toEqual(["KTC TE+", "IDPTC", "DLF IDP", "FP IDP"]);
    expect(result.reweighted).toEqual([]);
    expect(result.summary).toBe("(4 disabled)");
  });

  it("renders active badge with empty summary when isCustomized=true but received map is empty", () => {
    // Backend has stamped ``isCustomized: true`` but neither a
    // disabled source nor a weight override is in the received map
    // (e.g. a no-op override that the backend still flagged).  The
    // badge should render (active: true) but the summary string
    // should be empty — there is nothing to enumerate in the popover.
    const rankingsOverride = {
      isCustomized: true,
      enabledSources: ["ktcSfTep", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep", "fantasyProsIdp", "dlfIdp"],
      weights: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      defaults: { ktcSfTep: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0, dynastyNerdsSfTep: 1.0, fantasyProsIdp: 1.0, dlfIdp: 1.0 },
      received: {},
    };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(true);
    expect(result.disabled).toEqual([]);
    expect(result.reweighted).toEqual([]);
    expect(result.summary).toBe("");
  });

  it("is resilient to missing weights / defaults / received fields", () => {
    // Defensive check: a partially-populated override block should
    // not crash ``describeCustomMix`` — the helper must treat missing
    // fields as empty objects.  This guards against a future backend
    // shape drift that drops one of the sub-fields.
    const rankingsOverride = { isCustomized: true };
    const result = describeCustomMix(rankingsOverride);
    expect(result.active).toBe(true);
    expect(result.disabled).toEqual([]);
    expect(result.reweighted).toEqual([]);
    expect(result.summary).toBe("");
  });
});

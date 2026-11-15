import { describe, expect, it } from "vitest";
import { boardFirstActivePickYear, isRetiredPickClassRow } from "@/lib/pick-class-lifecycle";

const pick = (name) => ({ assetClass: "pick", name });

describe("board pick-class lifecycle reader", () => {
  it("reads the stamped first active class, falling back to currentDraftYear", () => {
    expect(
      boardFirstActivePickYear({ pickClassLifecycle: { firstActiveClass: 2028 }, currentDraftYear: 2027 }),
    ).toBe(2028);
    expect(boardFirstActivePickYear({ currentDraftYear: 2027 })).toBe(2027);
    expect(boardFirstActivePickYear({})).toBeNull();
    expect(boardFirstActivePickYear(null)).toBeNull();
  });

  it("retires classes before the active year with no hard-coded year", () => {
    expect(isRetiredPickClassRow(pick("2026 Early 1st"), 2027)).toBe(true);
    expect(isRetiredPickClassRow(pick("2027 Early 1st"), 2027)).toBe(false);
    expect(isRetiredPickClassRow(pick("2028 Pick 1.01"), 2027)).toBe(false);
    // a synthetic future roll retires 2027 the same way
    expect(isRetiredPickClassRow(pick("2027 Early 1st"), 2028)).toBe(true);
  });

  it("fails open: unknown lifecycle retires nothing; non-picks untouched", () => {
    expect(isRetiredPickClassRow(pick("2020 Early 1st"), null)).toBe(false);
    expect(isRetiredPickClassRow({ assetClass: "player", name: "2026 Guy" }, 2027)).toBe(false);
  });
});

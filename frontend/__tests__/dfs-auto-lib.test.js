import { describe, expect, it } from "vitest";
import { formatAge, formatLockEt, freshnessCopy, isAutoSlate, pickDefaultAutoSlate } from "@/lib/dfs";

describe("automatic slate helpers", () => {
  it("never shows an unknown freshness state as current", () => {
    expect(freshnessCopy("CURRENT").status).toBe("positive");
    expect(freshnessCopy("SOURCE_ERROR").status).toBe("negative");
    expect(freshnessCopy("SOMETHING_NEW")).toEqual({ status: "neutral", label: "SOMETHING_NEW" });
    expect(freshnessCopy(undefined).label).toBe("Unknown");
  });

  it("opens Main, else the next unlocked slate, never a locked one or the other platform's", () => {
    const s = (platform, slateKey, locked = false) => ({ platform, slateKey, freshness: { locked } });
    expect(pickDefaultAutoSlate([s("draftkings", "early"), s("draftkings", "main")], "draftkings").slateKey).toBe("main");
    expect(pickDefaultAutoSlate([s("draftkings", "main", true), s("draftkings", "primetime")], "draftkings").slateKey).toBe("primetime");
    expect(pickDefaultAutoSlate([s("fanduel", "main")], "draftkings")).toBeNull();
    expect(pickDefaultAutoSlate(null, "draftkings")).toBeNull();
  });

  it("formats lock time in Eastern and ages in minutes/hours", () => {
    expect(formatLockEt("2026-10-04T17:00:00+00:00")).toBe("Sun 1:00 PM ET");
    expect(formatLockEt("nope")).toBe("—");
    expect(formatAge(0.2)).toBe("just now");
    expect(formatAge(12)).toBe("12 min ago");
    expect(formatAge(185)).toBe("3 h ago");
    expect(formatAge(null)).toBe("—");
  });

  it("recognises an automatic slate by its provenance", () => {
    expect(isAutoSlate({ slate: { provenance: { sourceKind: "auto_derived" } } })).toBe(true);
    expect(isAutoSlate({ slate: { provenance: { sourceKind: "platform_csv" } } })).toBe(false);
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { hasUsefulElement, summarise, validateRunOptions } from "../../scripts/route-baseline-support.mjs";

afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

describe("route baseline validity", () => {
  it("rejects hidden streaming copies, loading skeletons, empty spacers, and zero geometry", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 100, height: 30 });
    for (const html of ['<div hidden><p class="ready">Player</p></div>', '<p class="ready"><span class="ds-skeleton">Loading</span></p>', '<p class="ready"></p>']) {
      document.body.innerHTML = html;
      expect(hasUsefulElement(".ready")).toBe(false);
    }
    document.body.innerHTML = '<p class="ready">A loaded player</p>';
    expect(hasUsefulElement(".ready")).toBe(true);
    HTMLElement.prototype.getBoundingClientRect.mockReturnValue({ width: 0, height: 0 });
    expect(hasUsefulElement(".ready")).toBe(false);
  });
  it("keeps failed samples and unobserved metrics visible, and never rounds CLS to zero", () => {
    const result = summarise([{ usefulMs: 80, cls: 0.072 }, { usefulMs: null }, { error: "auth" }]);
    expect(result.usefulMissing).toBe(2);
    expect(result.errors).toBe(1);
    expect(result.cls.p95).toBe(0.072);
    expect(result.inpMs).toEqual({ p50: null, p95: null, n: 0 });
  });
  it("refuses a vacuous or mislabeled measurement configuration", () => {
    const valid = { runs: 5, viewport: "mobile", cpu: 4, network: "4g", timeout: 45000, routes: ["/rankings"] };
    expect(() => validateRunOptions(valid, ["/rankings"])).not.toThrow();
    for (const invalid of [{ runs: 0 }, { cpu: 0 }, { viewport: "phone" }, { routes: ["/missing"] }, { network: "fast-ish" }]) {
      expect(() => validateRunOptions({ ...valid, ...invalid }, ["/rankings"])).toThrow();
    }
  });
});

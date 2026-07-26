import { describe, it, expect } from "vitest";
import { MORE_SECTIONS } from "@/lib/more-sections";

function allItems() {
  return MORE_SECTIONS.flatMap((s) => s.items);
}

describe("More hub sections", () => {
  it("every entry has href, label, and desc", () => {
    for (const item of allItems()) {
      expect(item.href).toMatch(/^\//);
      expect(item.label).toBeTruthy();
      expect(item.desc).toBeTruthy();
    }
  });

  it("includes News — /news is not in the 4-tab mobile bottom nav, so the hub is its mobile entry point", () => {
    const news = allItems().find((i) => i.href === "/news");
    expect(news).toBeTruthy();
    expect(news.label).toBe("News");
  });

  it("hrefs are unique", () => {
    const hrefs = allItems().map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});

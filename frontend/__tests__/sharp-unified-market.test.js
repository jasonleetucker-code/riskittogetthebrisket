import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const page = fs.readFileSync(path.join(process.cwd(), "app/market/sharp-tracker/page.jsx"), "utf8");
const route = fs.readFileSync(path.join(process.cwd(), "app/api/sharp/market/route.js"), "utf8");

describe("unified Sharp Tracker surface", () => {
  it("keeps one route and one table for both sources", () => {
    expect(page.match(/<table/g)?.length).toBe(1);
    expect(page).toContain("All sources");
    expect(page).toContain("Sleeper");
    expect(page).toContain("FFPC");
    expect(page).not.toContain("FFPC Tracker");
  });

  it("requests source-specific normalized data instead of hiding rows", () => {
    expect(page).toContain("platform: source");
    expect(page).toContain("/api/sharp/market?");
    expect(route).toContain('proxyGet("/api/sharp/market"');
    expect(route).toContain("searchParams");
  });

  it("labels automated and curated qualification separately", () => {
    expect(page).toContain("Automated Sharp Score");
    expect(page).toContain("Curated FFPC high-stakes cohort");
    expect(page).toContain("Mixed cohort");
  });
});

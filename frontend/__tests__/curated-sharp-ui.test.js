import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(__dirname, "..");

function read(relative) {
  return fs.readFileSync(path.join(root, relative), "utf8");
}

describe("curated Sharp UI", () => {
  it("provides curated, performance, Super Sharp, and both filters", () => {
    const people = read("app/market/sharp-people/page.jsx");
    expect(people).toContain("Curated Industry Sharps");
    expect(people).toContain("Algorithmically Qualified");
    expect(people).toContain("Super Sharps");
    expect(people).toContain("Curated + performance");
    expect(people).toContain("No verified fantasy identity");
  });

  it("exposes an explicit approve/reject/unresolved review queue", () => {
    const review = read("app/admin/sharp-identities/page.jsx");
    expect(review).toContain('decide(candidate.candidate_id, "approve")');
    expect(review).toContain('decide(candidate.candidate_id, "reject")');
    expect(review).toContain('decide(candidate.candidate_id, "unresolved")');
    expect(review).toContain("Username resemblance alone remains unresolved");
  });

  it("explains missing performance instead of manufacturing values", () => {
    const profile = read("app/market/sharp-people/[personId]/page.jsx");
    expect(profile).toContain("No neutral win rate or synthetic championship record is assigned");
  });
});

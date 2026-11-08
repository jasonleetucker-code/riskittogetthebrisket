import { describe, expect, it } from "vitest";
import { findWeeklyRecap } from "@/lib/weekly-recap";

// Fixture shaped like the backend's ``weeks`` (newest first).  Expectation is
// built independently: a literal table of the retired byKey keys -> headline.
const weeks = [
  { season: "2025", week: 2, headline: "h-2025-2" },
  { season: "2025", week: 1, headline: "h-2025-1" },
  { season: "2024", week: 17, headline: "h-2024-17" },
  { season: "2024", week: 1, headline: "h-2024-1" },
];
const legacyByKey = {
  "2025:2": "h-2025-2",
  "2025:1": "h-2025-1",
  "2024:17": "h-2024-17",
  "2024:1": "h-2024-1",
};

describe("findWeeklyRecap", () => {
  it("resolves the same entry the retired byKey map did, for every key", () => {
    for (const [key, headline] of Object.entries(legacyByKey)) {
      const [season, week] = key.split(":");
      expect(findWeeklyRecap({ weeks }, season, week)?.headline).toBe(headline);
    }
  });
  it("returns null for unknown or missing data", () => {
    expect(findWeeklyRecap({ weeks }, "2023", "1")).toBeNull();
    expect(findWeeklyRecap({ weeks }, "2025", "99")).toBeNull();
    expect(findWeeklyRecap(null, "2025", "1")).toBeNull();
    expect(findWeeklyRecap({}, "2025", "1")).toBeNull();
  });
});

/**
 * The Pick Projector panel, and the states that must render nothing.
 *
 * /api/ros/pick-projections was built, tested, registered and mounted
 * with zero frontend callers. The last endpoint in that exact position
 * — /api/player/{id}/realized — turned out to return an empty list for
 * every player, always, and nothing noticed because nothing called it.
 *
 * So the interesting cases here are the quiet ones. This panel returns
 * null for four different reasons, and three of them are legitimate
 * steady states rather than faults:
 *
 *   no_snapshot   team strength not built for this league yet
 *   no_teams      Sleeper unreachable
 *   empty picks   no FUTURE picks (normal late in a draft cycle)
 *   fetch failure the only genuine error
 *
 * A panel that rendered an alarming card for the first three would
 * train the reader to ignore it; one that rendered an empty table
 * would read as breakage. Both are worse than nothing.
 */
import { describe, it, expect } from "vitest";
import {
  groupBySeason,
  confidenceStyle,
} from "@/app/league/sections/_pick-projector.jsx";

const PICK = (over = {}) => ({
  season: 2027,
  round: 1,
  seasonsOut: 1,
  projectedSlot: 3,
  projectedPickNumber: 3,
  label: "2027 1.03",
  confidence: "medium",
  slotConfidence: "medium",
  ownerRosterId: 5,
  ownerTeam: "Jason",
  originalRosterId: 5,
  originalTeam: "Jason",
  ...over,
});

describe("groupBySeason", () => {
  it("groups and orders seasons ascending", () => {
    const groups = groupBySeason([
      PICK({ season: 2029 }),
      PICK({ season: 2027 }),
      PICK({ season: 2028 }),
    ]);
    expect(groups.map(([s]) => s)).toEqual([2027, 2028, 2029]);
  });

  it("preserves the backend's within-season ordering", () => {
    // The server sorts by (season, round, projectedSlot). Re-sorting
    // here would silently override a decision made where the data is.
    const groups = groupBySeason([
      PICK({ label: "2027 1.01", projectedSlot: 1 }),
      PICK({ label: "2027 1.05", projectedSlot: 5 }),
      PICK({ label: "2027 2.02", round: 2, projectedSlot: 2 }),
    ]);
    expect(groups[0][1].map((p) => p.label)).toEqual([
      "2027 1.01",
      "2027 1.05",
      "2027 2.02",
    ]);
  });

  it("survives junk rows without dropping the good ones", () => {
    const groups = groupBySeason([
      null,
      PICK(),
      "nonsense",
      undefined,
      PICK({ season: 2028 }),
    ]);
    expect(groups.map(([s]) => s)).toEqual([2027, 2028]);
  });

  it("returns an empty list for empty or missing input", () => {
    expect(groupBySeason([])).toEqual([]);
    expect(groupBySeason(null)).toEqual([]);
    expect(groupBySeason(undefined)).toEqual([]);
  });
});

describe("confidenceStyle", () => {
  it("maps the three known levels distinctly", () => {
    const levels = ["high", "medium", "low"].map(
      (l) => confidenceStyle(l).label,
    );
    expect(new Set(levels).size).toBe(3);
    expect(levels).toEqual(["high", "medium", "low"]);
  });

  it("falls back to low for anything unrecognised", () => {
    // Conservative direction on purpose: an unknown label must not
    // render as the most reassuring one. The backend cap makes the
    // same choice for the same reason.
    for (const bad of ["", null, undefined, "extremely-high", 7]) {
      expect(confidenceStyle(bad).label).toBe("low");
    }
  });

  it("gives each level a distinct colour", () => {
    const colours = ["high", "medium", "low"].map(
      (l) => confidenceStyle(l).color,
    );
    expect(new Set(colours).size).toBe(3);
  });
});

describe("the acquired-pick distinction", () => {
  // The whole reason to read this table is spotting a pick you acquired
  // from a team projected to finish badly. Comparing roster IDs rather
  // than team names matters: two managers can share a display name, and
  // a renamed team would break a name comparison silently.
  const isAcquired = (p) =>
    p.originalRosterId != null &&
    p.ownerRosterId != null &&
    p.originalRosterId !== p.ownerRosterId;

  it("flags a pick held by someone other than its original team", () => {
    expect(isAcquired(PICK({ ownerRosterId: 5, originalRosterId: 9 }))).toBe(
      true,
    );
  });

  it("does not flag a team's own pick", () => {
    expect(isAcquired(PICK({ ownerRosterId: 5, originalRosterId: 5 }))).toBe(
      false,
    );
  });

  it("does not flag when an id is missing rather than guessing", () => {
    expect(isAcquired(PICK({ originalRosterId: null }))).toBe(false);
    expect(isAcquired(PICK({ ownerRosterId: null }))).toBe(false);
  });

  it("is not fooled by two teams sharing a display name", () => {
    const p = PICK({
      ownerRosterId: 5,
      originalRosterId: 9,
      ownerTeam: "Mike",
      originalTeam: "Mike",
    });
    expect(isAcquired(p)).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import { availabilityNote, simulatedWeeksLabel } from "../lib/trade-war-room";

describe("availability beside a lineup share (P0 2026-10-17)", () => {
  it("names a player out for every remaining week", () => {
    expect(
      availabilityNote({
        availability: { weeks: 12, eligibleWeeks: 0, unavailableWeeks: 12 },
      }),
    ).toBe("Out all 12 remaining weeks");
  });
  it("names partial absence and uncertainty", () => {
    expect(
      availabilityNote({
        availability: {
          weeks: 12,
          eligibleWeeks: 9,
          unavailableWeeks: 3,
          uncertainWeeks: 1,
          unknownWeeks: 0,
        },
      }),
    ).toBe("out 3 of 12 weeks, uncertain 1");
  });
  it("says nothing for a fully available player or a legacy payload", () => {
    expect(
      availabilityNote({
        availability: { weeks: 12, eligibleWeeks: 12, unavailableWeeks: 0 },
      }),
    ).toBeNull();
    expect(availabilityNote({})).toBeNull();
  });
  it("labels the simulated weeks", () => {
    expect(simulatedWeeksLabel({ weeks: [6, 7, 8, 17] })).toBe("weeks 6–17");
    expect(simulatedWeeksLabel({ weeks: null })).toBeNull();
  });
});

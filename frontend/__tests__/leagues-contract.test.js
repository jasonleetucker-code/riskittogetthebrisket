import { describe, expect, it } from "vitest";

import { parseLeaguesResponse } from "@/lib/generated/leagues-contract";

const league = {
  key: "main",
  displayName: "Main",
  scoringProfile: "default",
  idpEnabled: false,
  bestBall: false,
  rosterSettings: { teamCount: 12, starters: { QB: 1 } },
  active: true,
};

describe("generated leagues contract", () => {
  it("accepts the public and current-user views", () => {
    const publicView = { leagues: [league], defaultKey: "main" };
    expect(parseLeaguesResponse(publicView)).toBe(publicView);
    const signedIn = {
      ...publicView,
      userDefaultKey: null,
      leagues: [{ ...league, userDefaultTeam: { ownerId: "mine", teamName: "My Team" } }],
    };
    expect(parseLeaguesResponse(signedIn)).toBe(signedIn);
  });

  it("refuses private and unexpected fields before the hook caches them", () => {
    expect(() => parseLeaguesResponse({ leagues: [{ ...league, sleeperLeagueId: "secret" }], defaultKey: "main" }))
      .toThrow("invalid_leagues_contract");
    expect(() => parseLeaguesResponse({ leagues: [{ ...league, userDefaultTeam: { ownerId: "other", teamName: "Other" } }], defaultKey: "main" }))
      .toThrow("invalid_leagues_contract");
    expect(() => parseLeaguesResponse({ leagues: [league], defaultKey: "main", usernameMap: {} }))
      .toThrow("invalid_leagues_contract");
  });

  it("refuses wrong types and missing required fields", () => {
    expect(() => parseLeaguesResponse({ leagues: [{ ...league, idpEnabled: "false" }], defaultKey: "main" }))
      .toThrow("invalid_leagues_contract");
    expect(() => parseLeaguesResponse({ leagues: [league] })).toThrow("invalid_leagues_contract");
  });
});

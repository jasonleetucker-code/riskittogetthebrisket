// Manager Intelligence Batch F — lib/manager-saved.js (display helpers only).
import { describe, expect, it } from "vitest";
import {
  alertStateText,
  atCap,
  boardCountText,
  boardRows,
  boardValueText,
  eventLine,
  formerNamesText,
  isSaved,
  leaderboardHref,
  leaderboardQuery,
  lookupHref,
  nameStateText,
  populationText,
  readLeaderboardParams,
  reasonText,
  refreshRows,
  saveBody,
  savedCapText,
  savedErrorMessage,
} from "@/lib/manager-saved";

const SAVED = {
  managers: [{ userId: "111", username: "alpha", displayName: "Alpha" }],
  count: 1,
  limit: 50,
};

describe("saved list helpers", () => {
  it("matches saved managers by user id only", () => {
    expect(isSaved(SAVED, "111")).toBe(true);
    expect(isSaved(SAVED, 111)).toBe(true);
    expect(isSaved(SAVED, "alpha")).toBe(false); // a username is never the key
    expect(isSaved(null, "111")).toBe(false);
  });

  it("saves by id and never sends a name", () => {
    expect(saveBody("111")).toEqual({ userId: "111" });
    expect(saveBody("111", { alerts: false })).toEqual({ userId: "111", alerts: false });
    expect(saveBody("alpha")).toBeNull();
    expect(saveBody("")).toBeNull();
  });

  it("states the cap", () => {
    expect(savedCapText(SAVED)).toBe("1 of 50 saved");
    expect(atCap(SAVED)).toBe(false);
    expect(atCap({ count: 50, limit: 50 })).toBe(true);
    // Unknown count or limit is unknown fullness — never "full".
    expect(atCap({ limit: 50 })).toBe(false);
    expect(atCap({ count: 50 })).toBe(false);
  });

  it("labels name freshness and former usernames", () => {
    expect(nameStateText({ nameState: "current" })).toBe("");
    expect(nameStateText({ nameState: "not_found" })).toMatch(/no longer finds/);
    expect(nameStateText({})).toMatch(/not re-checked/);
    expect(formerNamesText({ previousUsernames: ["old1", "old2"] })).toBe(
      "formerly @old1, @old2",
    );
    expect(formerNamesText({ previousUsernames: [] })).toBe("");
  });

  it("describes the activity-check state without inventing a zero", () => {
    expect(alertStateText({ alerts: false })).toBe("Alerts off");
    expect(alertStateText({ alertState: { seeded: false } })).toMatch(/Not checked yet/);
    expect(
      alertStateText({ alertState: { seeded: false, lastStatus: "rate_limited" } }),
    ).toMatch(/last attempt: rate limited/);
    const text = alertStateText({
      alertState: {
        seeded: true,
        lastCheckedAt: Date.UTC(2026, 9, 1, 12),
        lastStatus: "partial",
        lastAlertAt: null,
      },
    });
    expect(text).toMatch(/^Checked Oct 1, 2026 · some leagues not fully read$/);
  });

  it("links a saved manager to its lookup", () => {
    expect(lookupHref({ userId: "111", username: "alpha" })).toBe("/managers?username=alpha");
    expect(lookupHref({ userId: "111", username: null })).toBe("/managers?username=111");
  });

  it("maps errors to messages", () => {
    expect(savedErrorMessage(409, {})).toMatch(/full/);
    expect(savedErrorMessage(403, {})).toMatch(/Guest/);
    expect(savedErrorMessage(500, { message: "Server said" })).toBe("Server said");
  });
});

describe("new-activity check", () => {
  it("summarises events and the first-check baseline", () => {
    const rows = refreshRows({
      checked: [
        { userId: "1", displayName: "A", mode: "baseline_seeded", newEvents: [] },
        {
          userId: "2",
          displayName: "B",
          mode: "ok",
          newEvents: [
            {
              id: "tx:9",
              kind: "waiver",
              leagueName: "Alleys",
              added: ["Joe"],
              dropped: ["Bob"],
              faabBid: 0,
            },
          ],
        },
      ],
    });
    expect(rows[0].note).toMatch(/First check/);
    expect(eventLine(rows[1].events[0])).toBe(
      "Waiver claim in Alleys — added Joe; gave up Bob (FAAB $0)",
    );
  });
});

describe("leaderboards", () => {
  it("builds only named-population queries", () => {
    expect(leaderboardQuery({ population: "saved" })).toBe(
      "/api/manager-intel/leaderboard?population=saved",
    );
    expect(leaderboardQuery({ population: "league", leagueId: "42", window: "season" })).toBe(
      "/api/manager-intel/leaderboard?population=league&leagueId=42&window=season",
    );
    expect(leaderboardQuery({ population: "league", leagueId: "x" })).toBeNull();
    expect(leaderboardQuery({ population: "all" })).toBeNull();
    expect(leaderboardHref({ population: "league", leagueId: "42" })).toBe(
      "/managers/leaderboards?population=league&league=42",
    );
    expect(leaderboardHref({ population: "league", leagueId: "bad" })).toBeNull();
    expect(leaderboardHref()).toBe("/managers/leaderboards?population=saved");
  });

  it("reads deep-link params", () => {
    expect(readLeaderboardParams("?population=league&league=42")).toEqual({
      population: "league",
      leagueId: "42",
    });
    expect(readLeaderboardParams("?league=abc")).toEqual({ population: "saved", leagueId: "" });
    expect(readLeaderboardParams("")).toEqual({ population: "saved", leagueId: "" });
  });

  it("names the population and its n", () => {
    expect(
      populationText({ kind: "saved", label: "Your saved managers", n: 3, withData: 2 }),
    ).toBe("Your saved managers · 3 managers (2 with recent data)");
    expect(populationText({ kind: "league", label: "Current teams in Alleys", n: 1 })).toBe(
      "Current teams in Alleys · 1 team",
    );
    expect(boardCountText({ n: 2, unranked: [{}] }, { n: 3 })).toBe("2 of 3 ranked");
    expect(boardCountText({ n: 2 }, {})).toBe("2 ranked");
    expect(boardCountText({}, { n: 3 })).toBe("Ranked count unknown");
    expect(populationText({ kind: "saved", label: "Your saved managers" })).toBe(
      "Your saved managers · size unknown",
    );
  });

  it("lists ranked rows then unranked ones with the reason, never 0", () => {
    const rows = boardRows({
      rows: [{ id: "1", rank: 1, displayName: "A", value: 1234.4, userId: "11" }],
      unranked: [{ id: "2", displayName: "B", value: null, reason: "not_yet_read" }],
    });
    expect(rows.map((r) => [r.rank, r.name, r.value, r.reason])).toEqual([
      [1, "A", "1,234", ""],
      [null, "B", "—", "not read yet"],
    ]);
    expect(boardValueText(0)).toBe("0");
    expect(boardValueText(null)).toBe("—");
    expect(reasonText("some_new_reason")).toBe("some new reason");
  });
});

import { describe, expect, it } from "vitest";
import {
  errorMessage,
  exposureText,
  filterOptions,
  filterPlayers,
  formatBadge,
  formatValue,
  leagueStateLabel,
  playerLeagueRows,
  profileQuery,
  readRecent,
  recordText,
  rememberRecent,
  summaryTiles,
} from "@/lib/manager-intel";
import { PROFILE } from "./fixtures/manager-intel-profile";

function memoryStorage(initial = {}) {
  const store = { ...initial };
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = String(v);
    },
    store,
  };
}

describe("manager-intel helpers", () => {
  it("builds the profile query, omitting the default scope", () => {
    expect(profileQuery(" dynastyfan ")).toBe(
      "/api/manager-intel/profile?username=dynastyfan",
    );
    expect(profileQuery("a", "keeper")).toBe(
      "/api/manager-intel/profile?username=a&scope=keeper",
    );
  });

  it("missing stays missing: null values and unmeasurable exposure render a dash, never 0", () => {
    expect(formatValue(null)).toBe("—");
    expect(formatValue(undefined)).toBe("—");
    expect(formatValue(0)).toBe("0");
    expect(formatValue(9500)).toBe("9,500");
    expect(exposureText(null)).toBe("—");
    expect(exposureText({ owned: 1, eligibleLeagues: 0, share: null })).toBe(
      "—",
    );
    expect(exposureText({ owned: 7, eligibleLeagues: 12, share: 0.5833 })).toBe(
      "7 / 12 (58%)",
    );
  });

  it("filters by name, position and team", () => {
    const { players } = PROFILE;
    expect(
      filterPlayers(players, { query: "jeff" }).map((p) => p.playerId),
    ).toEqual(["4046"]);
    expect(
      filterPlayers(players, { position: "LB" }).map((p) => p.playerId),
    ).toEqual(["9999"]);
    expect(filterPlayers(players, { team: "MIN", position: "LB" })).toEqual([]);
    expect(filterOptions(players, "position")).toEqual(["LB", "WR"]);
  });

  it("joins a player's leagues to the league list with slot and format", () => {
    const rows = playerLeagueRows(PROFILE.players[0], PROFILE.leagues);
    expect(rows).toEqual([
      {
        leagueId: "L1",
        name: "Alpha Dynasty",
        slot: "Starter",
        format: "SF · TEP · IDP · 12 teams",
      },
      {
        leagueId: "L2",
        name: "Beta Dynasty",
        slot: "Bench",
        format: "1QB · Best ball · 10 teams",
      },
    ]);
    expect(formatBadge(null)).toBe("");
  });

  it("summary tiles read the backend summary and never sum a non-Superflex value", () => {
    const tiles = Object.fromEntries(
      summaryTiles(PROFILE).map((t) => [t.key, t]),
    );
    expect(tiles.value.value).toBe("9,500");
    expect(tiles.value.meta).toBe("1 of 2 spots priced");
    expect(tiles.players.value).toBe("2");
    expect(summaryTiles(null)).toEqual([]);
    const noSf = { ...PROFILE, summary: { ...PROFILE.summary, byFormat: {} } };
    expect(summaryTiles(noSf).find((t) => t.key === "value").value).toBe("—");
  });

  it("labels records, league states and errors", () => {
    expect(recordText({ wins: 4, losses: 2, ties: 0 })).toBe("4-2");
    expect(recordText({ wins: 4, losses: 2, ties: 1 })).toBe("4-2-1");
    expect(recordText(null)).toBe("—");
    expect(leagueStateLabel("rate_limited")).toMatch(/Rate-limited/);
    expect(errorMessage(404, {})).toMatch(/No Sleeper user/);
    expect(errorMessage(503, { message: "Switched off." })).toBe(
      "Switched off.",
    );
  });

  it("recent searches dedupe case-insensitively, cap at 8 and survive broken storage", () => {
    const storage = memoryStorage();
    rememberRecent("Alpha", storage);
    rememberRecent("beta", storage);
    expect(rememberRecent("alpha", storage)).toEqual(["alpha", "beta"]);
    for (let i = 0; i < 10; i += 1) rememberRecent(`u${i}`, storage);
    expect(readRecent(storage)).toHaveLength(8);
    expect(rememberRecent("bad name!", storage)).toHaveLength(8);
    expect(
      readRecent(memoryStorage({ "managerIntel.recent": "{not json" })),
    ).toEqual([]);
    const throwing = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readRecent(throwing)).toEqual([]);
    expect(rememberRecent("ok", throwing)).toEqual(["ok"]);
  });
});

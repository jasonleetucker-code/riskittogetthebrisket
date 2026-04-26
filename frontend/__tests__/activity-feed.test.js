import { describe, it, expect } from "vitest";
import { buildActivityEvents, filterEvents, familyOfPos } from "@/lib/activity-feed";

const FAKE_TEAMS = [
  { ownerId: "ownA", rosterId: "1", name: "Team A", players: ["Caleb Williams", "Bo Nix"] },
  { ownerId: "ownB", rosterId: "2", name: "Team B", players: ["Drake Maye"] },
];

const FAKE_RAW = {
  sleeper: {
    teams: FAKE_TEAMS,
    positions: {
      "100": { name: "Caleb Williams" },
      "200": { name: "Drake Maye" },
    },
    trades: [
      {
        transaction_id: "t1",
        roster_ids: ["1", "2"],
        adds: { "100": "2" },
        drops: { "100": "1" },
        status_updated: 1714000000000, // 2024-04-25
      },
    ],
  },
};

const FAKE_NEWS = [
  {
    id: "n1",
    headline: "Caleb Williams ankle update",
    body: "Out 2 weeks.",
    severity: "alert",
    ts: "2026-04-26T14:00:00Z",
    players: [{ name: "Caleb Williams" }],
    url: "https://news.example/caleb",
  },
  {
    id: "n2",
    headline: "Random other story",
    severity: "info",
    ts: "2026-04-25T14:00:00Z",
    players: [{ name: "Some Other Player" }],
  },
];

describe("buildActivityEvents", () => {
  it("merges trades + news into one chronological feed", () => {
    const events = buildActivityEvents(FAKE_RAW, FAKE_NEWS);
    expect(events.length).toBe(3);
    expect(events.map((e) => e.type)).toEqual(["news", "news", "trade"]);
    // Newest first.
    expect(events[0].id).toBe("news::n1");
  });

  it("trade event carries team names + player names", () => {
    const [, , trade] = buildActivityEvents(FAKE_RAW, FAKE_NEWS);
    expect(trade.type).toBe("trade");
    expect(trade.teamNames).toEqual(expect.arrayContaining(["Team A", "Team B"]));
    expect(trade.playerNames).toContain("Caleb Williams");
  });

  it("returns [] when given empty inputs", () => {
    expect(buildActivityEvents(null, null)).toEqual([]);
    expect(buildActivityEvents({}, [])).toEqual([]);
  });
});

describe("filterEvents", () => {
  const events = buildActivityEvents(FAKE_RAW, FAKE_NEWS);

  it("scope=roster keeps events that touch a roster player", () => {
    const filtered = filterEvents(events, {
      scope: "roster",
      rosterNames: ["Caleb Williams"],
    });
    // News for Caleb + trade involving Caleb.  Other news is dropped.
    expect(filtered.map((e) => e.id)).toEqual(["news::n1", "trade::t1"]);
  });

  it("scope=league keeps everything", () => {
    expect(filterEvents(events, { scope: "league" })).toHaveLength(3);
  });

  it("type filter respects all/trade/news", () => {
    expect(filterEvents(events, { type: "trade" })).toHaveLength(1);
    expect(filterEvents(events, { type: "news" })).toHaveLength(2);
    expect(filterEvents(events, { type: "all" })).toHaveLength(3);
  });

  it("scope=roster with no roster names returns []", () => {
    expect(filterEvents(events, { scope: "roster", rosterNames: [] })).toEqual([]);
  });

  it("is case-insensitive on player names", () => {
    const filtered = filterEvents(events, {
      scope: "roster",
      rosterNames: ["caleb williams"],
    });
    expect(filtered.length).toBeGreaterThan(0);
  });
});

describe("familyOfPos", () => {
  it("maps QB/RB/WR/TE", () => {
    expect(familyOfPos("QB")).toBe("QB");
    expect(familyOfPos("RB")).toBe("RB");
  });
  it("maps IDP variants", () => {
    expect(familyOfPos("EDGE")).toBe("DL");
    expect(familyOfPos("CB")).toBe("DB");
  });
});

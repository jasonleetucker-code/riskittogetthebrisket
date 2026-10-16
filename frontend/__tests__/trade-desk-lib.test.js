/**
 * lib/trade-desk — statuses are user-entered; the roster check is evidence.
 */
import { describe, expect, it } from "vitest";
import {
  DESK_STATUSES,
  deskBodyFromOffer,
  deskErrorText,
  lastMarked,
  rosterCheckText,
  statusLabel,
} from "@/lib/trade-desk";

describe("trade desk lib", () => {
  it("mirrors the backend status vocabulary in workflow order", () => {
    expect(DESK_STATUSES.map((s) => s.value)).toEqual([
      "idea",
      "candidate",
      "evaluated",
      "saved",
      "manually_sent",
      "accepted",
      "rejected",
      "expired",
    ]);
    expect(statusLabel("manually_sent")).toBe("Manually sent");
    expect(statusLabel("nope")).toBe("Unknown");
  });

  it("builds a create body from a generated offer, keeping ids and picks", () => {
    const body = deskBodyFromOffer(
      {
        send: [
          {
            name: "Our WR",
            position: "WR",
            assetId: "player:1",
            modelValue: 5000,
          },
        ],
        receive: [
          {
            name: "2027 Mid 1st",
            isPick: true,
            boardRowName: "2027 Pick 1.06",
          },
        ],
      },
      {
        leagueKey: "main",
        myTeam: "Us",
        opponent: "Them",
        source: "best_offers",
        runId: "abc123",
      },
    );
    expect(body).toEqual({
      leagueKey: "main",
      myTeam: "Us",
      opponent: "Them",
      source: "best_offers",
      sourceRunId: "abc123",
      send: [
        { name: "Our WR", isPick: false, assetId: "player:1", position: "WR" },
      ],
      receive: [
        { name: "2027 Mid 1st", isPick: true, boardRowName: "2027 Pick 1.06" },
      ],
    });
  });

  it("words the roster check as evidence, never as a status", () => {
    expect(rosterCheckText({ state: "unknown" })).toBe(
      "Roster check unavailable",
    );
    expect(rosterCheckText({ state: "current", picksNotChecked: 0 })).toBe(
      "Players still in place",
    );
    expect(rosterCheckText({ state: "current", picksNotChecked: 1 })).toMatch(
      /picks not checked/,
    );
    expect(
      rosterCheckText({ state: "changed", noLongerInPlace: ["Their RB"] }),
    ).toBe("Roster changed: Their RB no longer in place");
  });

  it("explains every refusal", () => {
    expect(deskErrorText("duplicate")).toMatch(/Already/);
    expect(deskErrorText("guest_read_only")).toMatch(/Guest/);
    expect(deskErrorText("whatever")).toMatch(/could not be updated/);
  });

  it("reads the last user mark", () => {
    expect(lastMarked({ statusHistory: [] })).toBeNull();
    expect(
      lastMarked({
        statusHistory: [
          { status: "candidate", at: "a", setBy: "user" },
          { status: "accepted", at: "b", setBy: "user" },
        ],
      }).status,
    ).toBe("accepted");
  });
});

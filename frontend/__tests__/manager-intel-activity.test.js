import { describe, expect, it } from "vitest";
import {
  activityQuery,
  attributionNote,
  coverageProblems,
  eventDateText,
  filterAcquisitions,
  filterFeed,
  filterTrades,
  formatDate,
  methodDetail,
  rosterStatusText,
  seasonOptions,
  signedValue,
  subsequentLabel,
  tradeCalculatorShare,
  tradeCalculatorUrl,
  valueReasonText,
} from "@/lib/manager-intel";
import { decodeTrade, encodeTrade, parseShareParam } from "@/lib/trade-share";
import {
  ACQUISITIONS,
  ACTIVITY,
  TRADE,
  UNPRICED_TRADE,
} from "./fixtures/manager-intel-activity";

describe("manager-intel activity helpers", () => {
  it("builds the activity query, omitting defaults", () => {
    expect(activityQuery(" fan ")).toBe(
      "/api/manager-intel/activity?username=fan",
    );
    expect(
      activityQuery("fan", {
        window: "season",
        season: "2025",
        league: "123",
        scope: "keeper",
      }),
    ).toBe(
      "/api/manager-intel/activity?username=fan&window=season&season=2025&league=123&scope=keeper",
    );
  });

  it("offers the current season and the two before it", () => {
    expect(seasonOptions("2026")).toEqual(["2026", "2025", "2024"]);
    expect(seasonOptions("")).toEqual([]);
  });

  it("an undated event stays undated — never epoch zero", () => {
    expect(formatDate(null)).toBe("Undated");
    expect(formatDate(0)).toBe("Undated");
    expect(eventDateText({ occurredAt: null })).toBe("Undated");
    expect(eventDateText(ACQUISITIONS[1])).toBe(
      "Undated (on or before May 1, 2026)",
    );
    expect(eventDateText(TRADE)).toBe("Oct 12, 2026");
  });

  it("filters trades by league and by what the manager acquired or sent", () => {
    const trades = ACTIVITY.trades;
    expect(filterTrades(trades, { league: "L2" }).map((t) => t.id)).toEqual([
      "tx:t2",
    ]);
    expect(
      filterTrades(trades, { query: "alpha", direction: "in" }).map(
        (t) => t.id,
      ),
    ).toEqual(["tx:t1"]);
    expect(filterTrades(trades, { query: "alpha", direction: "out" })).toEqual(
      [],
    );
    expect(
      filterTrades(trades, { query: "bravo", direction: "out" }).map(
        (t) => t.id,
      ),
    ).toEqual(["tx:t1", "tx:t2"]);
    expect(
      filterTrades(trades, { query: "2027 round", direction: "in" }).map(
        (t) => t.id,
      ),
    ).toEqual(["tx:t1"]);
  });

  it("filters acquisitions and the feed", () => {
    expect(
      filterAcquisitions(ACQUISITIONS, { method: "DRAFT" }).map((a) => a.id),
    ).toEqual(["draft:d1:18:player:R"]);
    expect(filterAcquisitions(ACQUISITIONS, { query: "bravo" })).toHaveLength(
      1,
    );
    expect(filterFeed(ACTIVITY.feed, { league: "L2" })).toHaveLength(1);
  });

  it("labels methods with FAAB and draft slot, and roster state", () => {
    expect(methodDetail(ACQUISITIONS[0])).toBe("Waiver · $12");
    expect(methodDetail(ACQUISITIONS[1])).toBe("Draft · 2.06");
    expect(methodDetail({ method: "FREE_AGENT", faabBid: null })).toBe(
      "Free agent",
    );
    expect(methodDetail({ method: "WAIVER", faabBid: 0 })).toBe("Waiver · $0");
    expect(rosterStatusText(ACQUISITIONS[0])).toBe("Bench");
    expect(rosterStatusText(ACQUISITIONS[1])).toBe("Not rostered");
    expect(rosterStatusText({ stillRostered: null })).toBe("Unknown");
    expect(subsequentLabel(ACQUISITIONS[1].subsequent)).toBe("Later dropped");
  });

  it("names leagues that were not fully read", () => {
    expect(coverageProblems(ACTIVITY)).toEqual([
      {
        leagueId: "L2",
        name: "Beta League",
        text: "transactions partly read (1 week missing)",
      },
    ]);
  });

  it("explains uncertain attribution and unpriced values", () => {
    expect(attributionNote(ACTIVITY.feed[1].attribution)).toMatch(
      /previous owner/,
    );
    expect(attributionNote(ACTIVITY.feed[0].attribution)).toBe("");
    expect(valueReasonText("pick_already_used")).toBe("pick already used");
    expect(signedValue(null)).toBe("—");
    expect(signedValue(-1200)).toBe("−1,200");
    expect(signedValue(0)).toBe("0");
  });

  it("round-trips a trade through the calculator share link", () => {
    const url = tradeCalculatorUrl(TRADE, encodeTrade);
    expect(url.startsWith("/trade?share=")).toBe(true);
    const decoded = parseShareParam(url.slice(url.indexOf("?")));
    // Each calculator side lists what that team SENDS.
    expect(decoded.sides.map((s) => s.name)).toEqual([
      "Dynasty Fan",
      "Rival Two",
    ]);
    expect(decoded.sides[0].players).toEqual(["Bravo Receiver"]);
    expect(decoded.sides[1].players).toEqual(["Alpha Back", "2027 Round 1"]);
    expect(decoded.truncated).toBe(false);
    const share = tradeCalculatorShare(TRADE);
    expect(share.faabOmitted).toBe(true);
    expect(share.complete).toBe(false);
    expect(share.missing).toEqual([]);
    expect(decodeTrade(url.split("share=")[1]).sides).toHaveLength(2);
  });

  it("an asset the board cannot name is left out of the link and reported", () => {
    const share = tradeCalculatorShare(UNPRICED_TRADE);
    expect(share.missing).toEqual(["Zed Unranked"]);
    expect(share.complete).toBe(false);
    const url = tradeCalculatorUrl(UNPRICED_TRADE, encodeTrade);
    const decoded = parseShareParam(url.slice(url.indexOf("?")));
    expect(decoded.sides[1].players).toEqual([]);
    expect(decoded.sides[0].players).toEqual(["Bravo Receiver"]);
  });

  it("no link when nothing in the trade can be named", () => {
    expect(
      tradeCalculatorUrl(
        {
          sides: [
            { displayName: "A", playersOut: [{ kind: "player", name: "X" }] },
          ],
        },
        encodeTrade,
      ),
    ).toBeNull();
  });
});

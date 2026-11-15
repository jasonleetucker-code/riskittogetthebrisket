/**
 * `offerEvidenceLines` — one offer's managerEvidence block as sentences.
 * Counts with their samples; never a grade, label or likelihood.
 */
import { describe, expect, it } from "vitest";
import { offerEvidenceLines } from "@/lib/manager-evidence";

const measured = {
  state: "measured",
  tradeCount: 4,
  positionsTheyWouldReceive: [
    { position: "RB", receivedBefore: 3, ofPlayersReceived: 7 },
    { position: "TE", receivedBefore: 0, ofPlayersReceived: 7 },
    { position: "UNRESOLVED", receivedBefore: null, ofPlayersReceived: 7 },
  ],
  picksTheyWouldReceive: {
    offeredToThem: 1,
    receivedBefore: 2,
    ofAssetsReceived: 9,
  },
  offerShapeForThem: "expanding",
  sameShapeBefore: 2,
  tradesWithRequester: 1,
  unresolvedPositionReceived: 0,
};

describe("offerEvidenceLines", () => {
  it("renders every count with its sample, zero included", () => {
    const out = offerEvidenceLines(measured);
    expect(out.available).toBe(true);
    expect(out.lines).toEqual([
      "Received 3 RB of 7 players acquired by trade",
      "Received 0 TE of 7 players acquired by trade",
      "Received 2 picks of 9 assets acquired by trade",
      "2 of 4 trades had this shape for them (expanding)",
      "1 trade completed with you",
    ]);
    expect(out.note).toBe(
      "From 4 completed trades. History, not a prediction.",
    );
  });

  it("says position counts are a floor when some positions were unresolved", () => {
    const out = offerEvidenceLines({
      ...measured,
      unresolvedPositionReceived: 2,
    });
    expect(out.note).toMatch(/2 received players had no resolvable position/);
  });

  it("omits the together count when the requester is unknown (null, not 0)", () => {
    const out = offerEvidenceLines({ ...measured, tradesWithRequester: null });
    expect(out.lines.some((l) => l.includes("with you"))).toBe(false);
  });

  it("explains every non-measured state instead of showing numbers", () => {
    expect(offerEvidenceLines(undefined).available).toBe(false);
    expect(
      offerEvidenceLines({
        state: "insufficient_sample",
        reason: "no_completed_trades_observed",
      }),
    ).toEqual({
      available: false,
      lines: [],
      note: "Manager history: no completed trades on record.",
    });
    expect(
      offerEvidenceLines({
        state: "unavailable",
        reason: "acquisition_store_missing",
      }).note,
    ).toMatch(/not collected on this server/);
  });

  it("never words a likelihood, grade or label", () => {
    const { lines, note } = offerEvidenceLines(measured);
    const text = [...lines, note].join(" ").toLowerCase();
    for (const word of [
      "likely",
      "probab",
      "chance",
      "strong",
      "fit",
      "prefers",
    ]) {
      expect(text).not.toContain(word);
    }
  });
});

describe("offerEvidenceLines with unrecorded counts", () => {
  it("drops a line whose count is unknown rather than printing null or 0", () => {
    const out = offerEvidenceLines({
      state: "measured",
      tradeCount: 3,
      positionsTheyWouldReceive: [
        { position: "RB", receivedBefore: null, ofPlayersReceived: 5 },
      ],
      picksTheyWouldReceive: {
        offeredToThem: 1,
        receivedBefore: null,
        ofAssetsReceived: null,
      },
      offerShapeForThem: "even",
      sameShapeBefore: null,
      tradesWithRequester: null,
      unresolvedPositionReceived: null,
    });
    expect(out.available).toBe(true);
    expect(out.lines).toEqual([]);
    expect(out.note).toBe(
      "From 3 completed trades. History, not a prediction.",
    );
  });
});

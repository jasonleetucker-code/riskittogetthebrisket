/**
 * The FAAB recommendation must survive the mobile breakpoint, and an
 * absent bid must say WHY.
 *
 * RED-FIRST. Written against `2bb62b996` (current main). Two defects
 * are pinned here, both visible on the deployed waiver page:
 *
 *  1. The "Best add/drop moves" board configures its FAAB column with
 *     `hideBelow: "md"`, which is `display: none` below 768px
 *     (`app/ds.css` — `.ds-col-hide-md`). The board therefore shows
 *     # / Add / Drop / Net gain / Tier on a phone and no bid at all,
 *     while the page still offers a FAAB bid-posture control. There is
 *     no other mobile surface for the number.
 *
 *  2. When no bid resolves, the cell renders a bare `—`. That single
 *     glyph currently stands for four genuinely different facts:
 *     bids were never fetched (no team picked, or the endpoint failed),
 *     the backend declined to price this player, the name was
 *     ambiguous, or the row simply is not on the backend's board.
 *     "MISSING IS NEVER ZERO" has a sibling — missing is never
 *     *unexplained* on a decision surface.
 *
 * Nothing here computes a bid. `lib/waiver-faab.js` indexes and looks
 * up backend-stamped figures and this adds only a REASON alongside the
 * same lookup — see that module's header for why a locally derived
 * dollar figure is forbidden on this page.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import { buildWaiverBidIndex, waiverBidStateForRow } from "@/lib/waiver-faab";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");

/** A `/api/waiver/suggestions` payload shaped like `WaiverCandidate.to_dict`
 *  (`src/trade/waiver.py:79`): the bid triplet, or `bid: null` when the
 *  engine priced nothing. */
const PAYLOAD = {
  by_position: {
    WR: [
      {
        name: "Emeka Egbuka",
        position: "WR",
        consensusValue: 3100,
        rank: 61,
        isRookie: true,
        bid: { aggressive: 22, reasonable: 15, lowball: 8 },
      },
      {
        name: "Unpriced Guy",
        position: "WR",
        consensusValue: 400,
        rank: null,
        isRookie: false,
        bid: null,
      },
    ],
    // Same display name, two positions — the index suppresses the
    // name-only fallback rather than guessing which one you meant.
    DL: [
      {
        name: "Two Ways",
        position: "DE",
        consensusValue: 900,
        rank: 500,
        isRookie: false,
        bid: { aggressive: 4, reasonable: 3, lowball: 1 },
      },
    ],
    TE: [
      {
        name: "Two Ways",
        position: "TE",
        consensusValue: 800,
        rank: 520,
        isRookie: false,
        bid: { aggressive: 3, reasonable: 2, lowball: 1 },
      },
    ],
  },
};

describe("waiverBidStateForRow — an absent bid names its reason", () => {
  const index = buildWaiverBidIndex(PAYLOAD);

  it("reports a priced bid verbatim", () => {
    const out = waiverBidStateForRow(index, { name: "Emeka Egbuka", pos: "WR" });
    expect(out.state).toBe("priced");
    expect(out.bid.reasonable).toBe(15);
    expect(out.bid.aggressive).toBe(22);
    expect(out.bid.lowball).toBe(8);
  });

  it("distinguishes 'bids were never fetched' from 'this player has none'", () => {
    // No index at all: no team selected, wrong league, or the endpoint
    // did not answer. The board is fine; the bid layer is absent.
    expect(waiverBidStateForRow(null, { name: "Emeka Egbuka", pos: "WR" }).state).toBe(
      "unavailable",
    );
    // Index present, player on it, backend declined to price him.
    expect(waiverBidStateForRow(index, { name: "Unpriced Guy", pos: "WR" }).state).toBe(
      "unpriced",
    );
    // Index present, player simply not on the backend's board.
    expect(waiverBidStateForRow(index, { name: "Nobody At All", pos: "RB" }).state).toBe(
      "unpriced",
    );
  });

  it("reports an ambiguous name as ambiguous, never as a guessed bid", () => {
    // Two different players share this display name. A row that cannot
    // say which one it means gets a reason, not somebody else's dollars.
    const out = waiverBidStateForRow(index, { name: "Two Ways", pos: null });
    expect(out.state).toBe("ambiguous");
    expect(out.bid).toBeNull();
  });

  it("never invents a figure for any non-priced state", () => {
    for (const args of [
      [null, { name: "Emeka Egbuka", pos: "WR" }],
      [index, { name: "Unpriced Guy", pos: "WR" }],
      [index, { name: "Two Ways", pos: null }],
      [index, null],
    ]) {
      const out = waiverBidStateForRow(...args);
      expect(out.state).not.toBe("priced");
      expect(out.bid).toBeNull();
    }
  });

  it("every state carries human-readable copy — no bare dash", () => {
    for (const s of ["unavailable", "unpriced", "ambiguous"]) {
      const out =
        s === "unavailable"
          ? waiverBidStateForRow(null, { name: "x", pos: "WR" })
          : s === "unpriced"
            ? waiverBidStateForRow(index, { name: "Unpriced Guy", pos: "WR" })
            : waiverBidStateForRow(index, { name: "Two Ways", pos: null });
      expect(out.label, `${s} needs a short label`).toBeTruthy();
      expect(out.label).not.toBe("—");
      expect(out.reason, `${s} needs an explanation`).toBeTruthy();
      expect(out.reason.length).toBeGreaterThan(20);
    }
  });
});

describe("the mobile breakpoint actually reveals the bid", () => {
  const css = fs.readFileSync(
    path.join(ROOT, "app/waivers/waivers.module.css"),
    "utf8",
  );

  it("a mobile-only bid surface exists in the stylesheet", () => {
    expect(
      /\.faabInline\b/.test(css),
      "no `.faabInline` rule — the phone has no surface for the bid",
    ).toBe(true);
  });

  it("it is HIDDEN at desktop width and SHOWN below the md breakpoint", () => {
    // Desktop keeps the dedicated sortable column; the inline chip is
    // the phone's copy of the same number and must not double up.
    const base = css.match(/\.faabInline\s*\{[^}]*\}/)?.[0] || "";
    expect(base, ".faabInline has no base rule").toBeTruthy();
    expect(/display:\s*none/.test(base), ".faabInline must be hidden by default").toBe(
      true,
    );

    // 768px is the canonical --breakpoint-md that `hideBelow: "md"`
    // uses in app/ds.css. Any other number here and the chip and the
    // column would either overlap or leave a gap with no bid at all.
    //
    // The stylesheet holds SEVERAL `width < 768px` blocks, so scan all
    // of them: matching only the first one tests whichever block
    // happens to be highest in the file, which is a property of
    // authoring order rather than of the breakpoint.
    const blocks = [
      ...css.matchAll(/@media\s*\(width\s*<\s*768px\s*\)\s*\{([\s\S]*?)\n\}/g),
    ].map((m) => m[1]);
    expect(blocks.length, "no `@media (width < 768px)` block").toBeGreaterThan(0);

    // READ the declared value; do not merely assert "not none" with a
    // lookahead. `display:\s*(?!none)` looks right and is vacuous:
    // `\s*` backtracks to zero width, so the lookahead lands on the
    // SPACE before `none` and trivially succeeds. Verified by mutation
    // — flipping this very rule to `display: none` left that version
    // of the test green, which is the defect it exists to catch.
    const declared = blocks
      .map((b) => b.match(/\.faabInline\s*\{[^}]*?display:[ \t]*([a-z-]+)/)?.[1])
      .filter(Boolean);
    expect(
      declared.length,
      "no `.faabInline` display declaration inside a `width < 768px` block",
    ).toBeGreaterThan(0);
    expect(
      declared.some((v) => v !== "none"),
      `below 768px \`.faabInline\` must become visible — declared: ${declared.join(", ")}`,
    ).toBe(true);
  });
});

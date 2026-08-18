/**
 * Mobile and desktop must be served the SAME BOARD.
 *
 * `frontend/lib/device-profile.js::preferredDataView()` routes mobile and
 * slow-network clients to `/api/data?view=compact` and everyone else to
 * `?view=array`.  Responsive LAYOUT may differ; the business answer may
 * not.  Until 2026-08-18 it did: `compact` pruned 14 fields that
 * `_materializePlayerArrayRow` reads, so the same player on the same day
 * rendered a different Flagged count (`/edge`), a different confidence
 * string, a collapsed value-derivation chain (`PlayerPopup`) and — because
 * `blendedSourceRank` is a SORT KEY — a different Consensus ORDER.
 *
 * `tests/api/test_compact_view_consumer_parity.py` pins the same invariant
 * statically, by parsing the materializer's reads.  This spec pins it
 * against a running server, which is what catches a divergence introduced
 * anywhere between the pipeline and the wire — a view branch in `server.py`,
 * a stale precomputed payload, a proxy that rewrites one view and not the
 * other.  Two instruments, because the failure was invisible to both the
 * backend shape test and the whole frontend suite.
 *
 * Runs on one project: it drives the API directly, so a second viewport
 * would re-measure the same bytes.  The viewport does not choose the view
 * here — the request does, which is precisely what makes the comparison
 * possible at all.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { desktopOnly } = require("../helpers/journey");

/**
 * `sourceRankMeta` is compared SEPARATELY, and that is not a loophole.
 *
 * It is the one field the compact view legitimately reshapes: the whole
 * object is kept but each per-source entry is reduced to the subset the UI
 * consumes (`_SLIM_SOURCE_RANK_META_FIELDS` in `src/api/compact_view.py`).
 * Comparing it wholesale therefore reports a difference on ~800 rows that
 * is by design, and — worse — that expected noise would mask a real
 * divergence inside it.
 *
 * So the four consumed subfields are compared exactly, per source, and the
 * audit stamps around them are not.  `percentile`, `isAnchor`, `ladderDepth`,
 * `valueContributionPath` and `tepBoostApplied` were each checked against
 * the whole frontend and have no reader.
 */
const CONSUMED_SOURCE_META_FIELDS = [
  "valueContribution",
  "appliedWeight",
  "effectiveWeight",
  "method",
];

/**
 * Every field `_materializePlayerArrayRow` reads off a contract player row,
 * minus `sourceRankMeta` (above).
 *
 * Kept as an explicit list rather than derived, because this file cannot
 * import the ES module and a silent under-derivation would make the whole
 * spec pass vacuously.  `test_compact_view_consumer_parity.py` owns the
 * derived check; the guard test below owns the "this list is not stale" one
 * — and it earned its keep immediately, catching `marketCorridorClamp`
 * missing from a first draft of this list.
 */
const MATERIALIZED_FIELDS = [
  "age",
  "alphaShrinkage",
  "anchorValue",
  "anomalyFlags",
  "assetClass",
  "blendedSourceRank",
  "canonicalConsensusRank",
  "canonicalName",
  "canonicalSiteValues",
  "canonicalTierId",
  "confidenceBucket",
  "confidenceLabel",
  "displayName",
  "droppedSources",
  "effectiveSourceRanks",
  "hasSourceDisagreement",
  "identityMethod",
  "identityResolutionConfidence",
  "isSingleSource",
  "madPenaltyApplied",
  "marketBreadthAgreementIndex",
  "marketConfidence",
  "marketCorridorClamp",
  "marketGapDirection",
  "marketGapMagnitude",
  "marketGapValueRatio",
  "playerId",
  "position",
  "quarantined",
  "rankChange",
  "rankDerivedValue",
  "rankHistory",
  "rawSourceValues",
  "rookie",
  "softFallbackCount",
  "sourceCount",
  "sourceNativeValues",
  "sourceOriginalRanks",
  "sourceRankPercentileSpread",
  "sourceRankSpread",
  "sourceRanks",
  "sourceSpread",
  "subgroupBlendValue",
  "subgroupDelta",
  "team",
  "twoWayPlayerBoost",
  "yearsExp",
];

/** Stable identity for a row, matching what `buildRows` keys on. */
function rowKey(row) {
  return String(row?.playerId || row?.displayName || row?.canonicalName || "");
}

async function fetchView(page, view) {
  const res = await page.request.get(`/api/data?view=${view}`);
  expect(res.status(), `GET /api/data?view=${view}`).toBe(200);
  const body = await res.json();
  const rows = Array.isArray(body?.playersArray) ? body.playersArray : [];
  expect(rows.length, `view=${view} served no playersArray`).toBeGreaterThan(0);
  return { body, rows, byKey: new Map(rows.map((r) => [rowKey(r), r])) };
}

test.describe("api: mobile/desktop view parity", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("compact and array serve the same players", async ({
    authedPage: page,
  }) => {
    const array = await fetchView(page, "array");
    const compact = await fetchView(page, "compact");

    expect(compact.rows.length, "row count differs between views").toBe(
      array.rows.length,
    );
    const missing = [...array.byKey.keys()].filter((k) => !compact.byKey.has(k));
    expect(missing.slice(0, 10), "players present on desktop but not mobile").toEqual(
      [],
    );
  });

  test("every field the materializer reads is identical in both views", async ({
    authedPage: page,
  }) => {
    const array = await fetchView(page, "array");
    const compact = await fetchView(page, "compact");

    // Report ALL divergent fields, not the first: the original defect hit
    // fourteen at once, and a first-failure message would have sent the
    // next reader chasing one field through fourteen rounds.
    const divergent = new Map();
    for (const [key, desktopRow] of array.byKey) {
      const mobileRow = compact.byKey.get(key);
      if (!mobileRow) continue;
      for (const field of MATERIALIZED_FIELDS) {
        const a = JSON.stringify(desktopRow[field] ?? null);
        const b = JSON.stringify(mobileRow[field] ?? null);
        if (a === b) continue;
        if (!divergent.has(field)) divergent.set(field, { count: 0, sample: null });
        const entry = divergent.get(field);
        entry.count += 1;
        if (!entry.sample) entry.sample = { player: key, desktop: a, mobile: b };
      }
    }
    expect(
      Object.fromEntries(divergent),
      "fields the frontend renders differ between the mobile and desktop views",
    ).toEqual({});
  });

  test("the consumed sourceRankMeta subfields are identical in both views", async ({
    authedPage: page,
  }) => {
    // The compact view slims each per-source entry, so this is the one
    // field where "identical object" is the wrong question and "identical
    // where it is read" is the right one.  Every value cell, the trade
    // per-source winner card and the rankings audit popover read these
    // four; if any of them moved between views, the board would disagree
    // with itself at exactly the place a user goes to check it.
    const array = await fetchView(page, "array");
    const compact = await fetchView(page, "compact");

    const divergent = new Map();
    for (const [key, desktopRow] of array.byKey) {
      const mobileRow = compact.byKey.get(key);
      if (!mobileRow) continue;
      const dMeta = desktopRow.sourceRankMeta || {};
      const mMeta = mobileRow.sourceRankMeta || {};
      const sources = new Set([...Object.keys(dMeta), ...Object.keys(mMeta)]);
      for (const src of sources) {
        for (const field of CONSUMED_SOURCE_META_FIELDS) {
          const a = JSON.stringify(dMeta[src]?.[field] ?? null);
          const b = JSON.stringify(mMeta[src]?.[field] ?? null);
          if (a === b) continue;
          const label = `${src}.${field}`;
          if (!divergent.has(label)) {
            divergent.set(label, { count: 0, sample: { player: key, desktop: a, mobile: b } });
          }
          divergent.get(label).count += 1;
        }
      }
    }
    expect(
      Object.fromEntries(divergent),
      "per-source meta the UI reads differs between the mobile and desktop views",
    ).toEqual({});
  });

  test("the deliberately-pruned fields are the ONLY per-row difference", async ({
    authedPage: page,
  }) => {
    // Stated positively, over EVERY key on the row rather than a list this
    // file maintains — so a field added to the contract tomorrow, pruned
    // by accident, and never added to MATERIALIZED_FIELDS still fails here.
    //
    // The three exceptions are the prune list, and `sourceRankMeta` is the
    // slimming carved out above.  Anything else appearing in this set is a
    // divergence nobody decided on.
    const ALLOWED = new Set([
      "hillValueSpread",
      "marketDispersionCV",
      "pickDetails",
      "sourceRankMeta",
    ]);
    const array = await fetchView(page, "array");
    const compact = await fetchView(page, "compact");

    const unexpected = new Map();
    for (const [key, desktopRow] of array.byKey) {
      const mobileRow = compact.byKey.get(key);
      if (!mobileRow) continue;
      const fields = new Set([...Object.keys(desktopRow), ...Object.keys(mobileRow)]);
      for (const field of fields) {
        if (ALLOWED.has(field)) continue;
        const a = JSON.stringify(desktopRow[field] ?? null);
        const b = JSON.stringify(mobileRow[field] ?? null);
        if (a === b) continue;
        if (!unexpected.has(field)) {
          unexpected.set(field, { count: 0, sample: { player: key, desktop: a.slice(0, 200), mobile: b.slice(0, 200) } });
        }
        unexpected.get(field).count += 1;
      }
    }
    expect(
      Object.fromEntries(unexpected),
      "a field differs between the views that nobody decided to prune",
    ).toEqual({});
  });

  test("the contract-level blocks the board renders survive both views", async ({
    authedPage: page,
  }) => {
    const array = await fetchView(page, "array");
    const compact = await fetchView(page, "compact");
    // `methodology` used to be pruned, so /rankings' methodology section
    // was absent on mobile and present on desktop.
    for (const block of ["methodology", "meta", "sleeper"]) {
      expect(
        Boolean(compact.body?.[block]),
        `view=compact dropped '${block}', which view=array carries`,
      ).toBe(Boolean(array.body?.[block]));
    }
    expect(compact.body?.meta?.view).toBe("compact");
  });

  test("compact is smaller on the wire than array", async ({
    authedPage: page,
  }) => {
    // The promise the view's NAME makes, checked where it is actually
    // kept — over HTTP, with the server's own gzip in play.  It was
    // inverted for months (compact +16.3% vs array) because the only
    // measurement anyone had was a comment.
    const sizes = {};
    for (const view of ["array", "compact"]) {
      const res = await page.request.get(`/api/data?view=${view}`, {
        headers: { "accept-encoding": "gzip" },
      });
      expect(res.status()).toBe(200);
      sizes[view] = (await res.body()).length;
    }
    expect(
      sizes.compact,
      `compact ${sizes.compact} B vs array ${sizes.array} B — the view served ` +
        "to phones and slow connections is the larger one",
    ).toBeLessThan(sizes.array);
  });

  test("guard: the materialized-field list still matches the materializer", async () => {
    // Without this, deleting entries from MATERIALIZED_FIELDS would make
    // every assertion above pass while checking less — the exact shape of
    // the bug this spec exists for.
    const fs = require("node:fs");
    const path = require("node:path");
    const src = fs.readFileSync(
      path.join(__dirname, "..", "..", "..", "frontend", "lib", "dynasty-data.js"),
      "utf8",
    );
    const start = src.indexOf("function _materializePlayerArrayRow");
    expect(start, "could not find the materializer").toBeGreaterThan(-1);
    let depth = 0;
    let end = src.indexOf("{", start);
    for (let i = end; i < src.length; i++) {
      if (src[i] === "{") depth += 1;
      else if (src[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    const body = src.slice(start, end + 1);
    const read = new Set(
      [...body.matchAll(/\bplayer\.([A-Za-z_][A-Za-z0-9_]*)/g)].map((m) => m[1]),
    );
    // Deliberate exclusions, each with a reason.
    read.delete("identityConfidence"); // deprecated alias emitted beside the canonical name
    read.delete("_sleeperId"); // underscore compat mirror, read with a ?? fallback
    read.delete("_yearsExp"); // same
    // Compared by the dedicated subfield test rather than wholesale.
    const listed = new Set([...MATERIALIZED_FIELDS, "sourceRankMeta"]);
    const unlisted = [...read].filter((f) => !listed.has(f)).sort();
    expect(unlisted, "the materializer reads fields this spec does not compare").toEqual(
      [],
    );
  });
});

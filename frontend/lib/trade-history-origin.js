/**
 * trade-history-origin — "this calculator trade came from Trade History"
 * (TC-B2 / TCM-N03), WITHOUT touching any URL.
 *
 * A completed trade opened from /trades lands in the calculator in LIVE mode:
 * today's values, rosters and needs, not the league as it was when the trade
 * was made (the as-of replay of HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md
 * §9 is not built).  The share-link format is FROZEN (owner closeout
 * 2026-10-18, decision 10: no URL changes until a coordinated compatibility
 * migration), so the origin travels as a same-tab session hand-off keyed to
 * the exact share payload the link carries:
 *
 *   /trades, on click   rememberHistoryOrigin(encodedShare, tradedAt)
 *   /trade, on restore  historyOriginFor(encodedShare)  -> { tradedAt } | null
 *
 * A link opened any other way (pasted, another tab, another device) carries
 * no hand-off and shows no banner -- an absent note, never a wrong one.
 * Storage failures (private mode, blocked storage) are the same: no note.
 */

export const HISTORY_ORIGIN_STORAGE_KEY = "trade_history_origin_v1";

function storage() {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

/** Record that `encodedShare` is being opened from Trade History. */
export function rememberHistoryOrigin(encodedShare, tradedAt = null) {
  const s = storage();
  if (!s || !encodedShare) return;
  try {
    s.setItem(
      HISTORY_ORIGIN_STORAGE_KEY,
      JSON.stringify({
        share: String(encodedShare),
        tradedAt: tradedAt ? String(tradedAt).slice(0, 40) : null,
      }),
    );
  } catch {
    /* storage blocked: no note, by design */
  }
}

/** `{ tradedAt }` when `encodedShare` was opened from Trade History in this tab, else null. */
export function historyOriginFor(encodedShare) {
  const s = storage();
  if (!s || !encodedShare) return null;
  try {
    const saved = JSON.parse(s.getItem(HISTORY_ORIGIN_STORAGE_KEY) || "null");
    if (!saved || saved.share !== String(encodedShare)) return null;
    return { tradedAt: saved.tradedAt || null };
  } catch {
    return null;
  }
}

/** The share payload in a `?share=` search string, or null. */
export function sharePayloadOf(search) {
  try {
    return new URLSearchParams(String(search || "")).get("share") || null;
  } catch {
    return null;
  }
}

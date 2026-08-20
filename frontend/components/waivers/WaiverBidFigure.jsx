"use client";

/**
 * WaiverBidFigure — the ONE renderer for a backend-stamped FAAB bid on
 * /waivers.
 *
 * Used twice by the "Best add/drop moves" board: once as the desktop
 * column cell, once as the inline chip the phone gets beside each add.
 * One component rather than two, because two printers for one dollar
 * figure is exactly how the compact-view parity break (`F-13`) let
 * mobile and desktop render different numbers for the same player.
 *
 * ── It renders; it does not compute ───────────────────────────────
 * Every figure arrives from `src/trade/faab_engine.py` through
 * `/api/waiver/suggestions` and is resolved by
 * `lib/waiver-faab.js::waiverBidStateForRow`. There is no fallback
 * arithmetic here — no scale, no cap, no floor. The deleted
 * `computeFaabHint` (see the closing note in `lib/waiver-logic.js`) is
 * precisely what this must never become.
 *
 * ── Three quantities, kept apart ──────────────────────────────────
 * `docs/faab-model.md` separates what a player is WORTH (the objective
 * ceiling, a share of the league's ORIGINAL budget) from what THIS
 * team should BID, and the bid desk's posture shapes only the latter.
 * The triplet this component prints is the engine's bid ladder off the
 * objective ceiling (`src/trade/waiver.py::bid_range`: aggressive =
 * ceiling × budget, reasonable = 0.70 of it, lowball = 0.35). It is
 * NOT the posture-parameterised recommendation — that comes from
 * `/api/waiver/faab-recommend` in the bid desk, and the suggestions
 * endpoint neither accepts nor applies `riskPosture`. So the copy here
 * says "FAAB bid" and points at the desk; it must not be relabelled as
 * "your recommended bid" without the backend actually computing one
 * per row.
 *
 * ── An absence states its reason ──────────────────────────────────
 * A bare `—` stood for four different facts. `entry.state` names which
 * one, and the label is rendered instead of the glyph.
 */

import styles from "@/app/waivers/waivers.module.css";

/** Whole dollars. Unit formatting, not math — the engine already
 *  rounded (`_round_half_up`), and rounding twice would move a
 *  published number. */
function fmtDollars(n) {
  return `$${Number(n).toLocaleString()}`;
}

export default function WaiverBidFigure({ entry, inline = false }) {
  const state = entry?.state || "unavailable";
  const priced = state === "priced" && Number.isFinite(Number(entry?.bid?.reasonable));

  const className = [
    styles.faabFigure,
    inline ? styles.faabInline : "",
    priced ? "" : styles.faabAbsent,
  ]
    .filter(Boolean)
    .join(" ");

  if (!priced) {
    return (
      <span
        className={className}
        data-testid="waiver-bid-figure"
        data-state={state}
        title={entry?.reason || ""}
      >
        {entry?.label || "Not priced"}
      </span>
    );
  }

  const { reasonable, aggressive, lowball } = entry.bid;
  // The ladder ends ride along as a `title` on desktop and as visible
  // small print inline, so a phone user is not asked to hover.
  const detail =
    `lowball ${fmtDollars(lowball)} · aggressive ${fmtDollars(aggressive)}`;

  return (
    <span
      className={className}
      data-testid="waiver-bid-figure"
      data-state="priced"
      title={`Reasonable ${fmtDollars(reasonable)} · ${detail}`}
    >
      {inline ? <span className={styles.faabInlineLabel}>FAAB bid</span> : null}
      <span className={styles.faabAmount}>{fmtDollars(reasonable)}</span>
      <span className={styles.faabDetail} data-testid="waiver-bid-detail">
        {detail}
      </span>
    </span>
  );
}

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
 * ── Four quantities, kept apart ───────────────────────────────────
 * `docs/faab-model.md` separates what a player is WORTH (the objective
 * ceiling, "Max Worth") from what THIS team should BID, and further
 * separates the bid from what the MARKET is expected to clear at and
 * from the most this budget could rationally pay. All four now come
 * from the same market-aware engine call `find_waiver_targets` already
 * makes per candidate (`src/trade/faab_engine.py::recommend`) — this
 * component used to print a fixed 70%/35%-of-ceiling ladder
 * (`lowball`/`aggressive`) that had NO rival model in it at all, which
 * is exactly the bug this redesign replaces. It is NOT the
 * posture-parameterised recommendation from the bid desk
 * (`/api/waiver/faab-recommend`) — the suggestions endpoint neither
 * accepts nor applies `riskPosture` — but it IS the same rival-
 * contention engine, unlike the retired ladder.
 *
 * `entry.bid.reasonable` is the headline "Bid". `clearing`/
 * `clearingLow`/`clearingHigh` are a real quantile band of the modelled
 * rival-bid distribution (`faab_engine.py::_market_clearing_price`),
 * not a fabricated range. `maxRational` is the ceiling on what this
 * budget could rationally pay (never above the balance). All three are
 * `null` in `ceiling_only_estimate` mode — see `waiverBidStateForRow`'s
 * `team_context_missing` state, which withholds this component
 * entirely in that case rather than rendering nulls as dashes.
 *
 * ── An absence states its reason ──────────────────────────────────
 * A bare `—` stood for four different facts. `entry.state` names which
 * one (a fifth, `team_context_missing`, says explicitly that a number
 * exists on the payload but is being withheld because it is not a
 * recommendation), and the label is rendered instead of the glyph.
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

  const { reasonable, clearing, clearingLow, clearingHigh, maxRational, objectiveDollars, confidence } =
    entry.bid;

  // Real market-aware fields, all present together or all null — see
  // to_dict() on WaiverCandidate. Older cached payload shapes (or a
  // transitional deploy) fall back to the bare headline bid rather
  // than rendering half-built punctuation.
  const hasMarketDetail =
    Number.isFinite(clearingLow) && Number.isFinite(clearingHigh) && Number.isFinite(maxRational);

  const detail = hasMarketDetail
    ? `Expected clearing ${fmtDollars(clearingLow)}–${fmtDollars(clearingHigh)} · Max I'd pay ${fmtDollars(maxRational)}`
    : "";

  const tooltipParts = [`Bid ${fmtDollars(reasonable)}`];
  if (Number.isFinite(clearing)) tooltipParts.push(`Clearing (median) ${fmtDollars(clearing)}`);
  if (Number.isFinite(objectiveDollars)) tooltipParts.push(`Max Worth ${fmtDollars(objectiveDollars)}`);
  if (confidence) tooltipParts.push(`Confidence: ${confidence}`);

  return (
    <span
      className={className}
      data-testid="waiver-bid-figure"
      data-state="priced"
      title={tooltipParts.join(" · ")}
    >
      {inline ? <span className={styles.faabInlineLabel}>Bid</span> : null}
      <span className={styles.faabAmount}>{fmtDollars(reasonable)}</span>
      {detail ? (
        <span className={styles.faabDetail} data-testid="waiver-bid-detail">
          {detail}
        </span>
      ) : null}
    </span>
  );
}

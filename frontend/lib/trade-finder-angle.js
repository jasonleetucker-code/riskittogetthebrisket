// /angle threshold copy — what the server's two gates actually guaranteed.
//
// src/trade/angle.py keeps a package only when
//   my_gain_pct     >= min_my_gain_pct       (a FLOOR on your board), and
//   market_gain_pct <= max_market_gain_pct   (a CEILING on the market — the
//                                             gap may be any amount below it).
// The page used to say each package "stays within ±N%" on the market, which
// claimed a lower bound the server never applies, and it read N from the live
// form inputs, which can change after the search ran.  The numbers here come
// from the `thresholds` block the server returned with the result; when that
// block is missing the copy says so instead of substituting the inputs.

function finite(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function fmtPct(n) {
  const text = Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (n > 0) return `+${text}%`;
  if (n < 0) return `-${text}%`;
  return "0%";
}

/** The two gates the server applied, or null when it did not report them. */
export function appliedAngleThresholds(result) {
  const t = result?.thresholds;
  const minMyGain = finite(t?.min_my_gain_pct);
  const maxMarketGap = finite(t?.max_market_gain_pct);
  if (minMyGain === null || maxMarketGap === null) return null;
  return { minMyGain, maxMarketGap };
}

/** Subtitle for the results panel. */
export function angleResultsSubtitle(result) {
  const t = appliedAngleThresholds(result);
  if (!t) {
    return "Each package passed the server's board-gain floor and market-gap ceiling; the server did not report their values.";
  }
  return (
    `Each package gains at least ${fmtPct(t.minMyGain)} on your board, and on the market the ` +
    `other side consults you receive at most ${fmtPct(t.maxMarketGap)} more than you give ` +
    `(a ceiling only — the market gap can be lower).`
  );
}

/** Empty-state description when nothing cleared both gates. */
export function angleNoResultDescription(result, targetTeamName) {
  const t = appliedAngleThresholds(result);
  const against = targetTeamName ? ` against ${targetTeamName}` : "";
  const bar = t
    ? `Nothing gains at least ${fmtPct(t.minMyGain)} on your board with a market gap of at most ${fmtPct(t.maxMarketGap)}`
    : "Nothing cleared the server's board-gain and market-gap thresholds";
  return `${bar} with this selection${against}. Try a different selection, loosen the thresholds under Advanced, or remove the team filter.`;
}

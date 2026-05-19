// Effective auction power — JS mirror of src/api/auction_power.py.
//
// The Python module is the source of truth (and the documented home of
// the Phase 2 mini-auction simulation + the unit tests that pin the
// economic invariants).  This is a presentation-layer lens: it is
// computed entirely client-side from the raw per-team auction dollars
// the page already has — no extra backend payload, and it never
// touches the canonical $ or the global rankings board.
//
// Keep the math and constants in lockstep with
// effective_auction_power(); see that module's docstring for the
// rationale (zero-sum, S-shaped premium, saturating, leapfrog).

export const AP_PREMIUM_GAIN = 0.35;
export const AP_CURVATURE = 1.25;
export const AP_LEAPFROG_WEIGHT = 0.15;

function median(arr) {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function roundPreservingTotal(values, total) {
  const floors = values.map((v) => Math.floor(v));
  const deficit = total - floors.reduce((a, b) => a + b, 0);
  if (deficit <= 0) return floors;
  const rema = values
    .map((v, i) => ({ frac: v - Math.floor(v), i }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i);
  for (let k = 0; k < deficit; k++) floors[rema[k].i] += 1;
  return floors;
}

// totalsObj: { team: rawDollars } -> { team: effectiveDollars }.
// Zero-sum: the result sums to the same league total as the input.
export function effectiveAuctionPower(totalsObj) {
  const names = Object.keys(totalsObj);
  const raw = names.map((n) => Number(totalsObj[n]) || 0);
  const grand = Math.round(raw.reduce((a, b) => a + b, 0));
  const identity = () => {
    const r = roundPreservingTotal(raw, Math.max(grand, 0));
    return Object.fromEntries(names.map((n, i) => [n, r[i]]));
  };
  if (names.length < 2 || grand <= 0) return identity();

  const med = median(raw);
  const mad = median(raw.map((v) => Math.abs(v - med)));
  const spread = Math.max(mad * 1.4826, 0.01 * (grand / names.length));
  if (spread <= 0) return identity();

  const weighted = raw.map(
    (v) => v * (1 + AP_PREMIUM_GAIN * Math.tanh((v - med) / spread / AP_CURVATURE)),
  );
  const order = raw.map((_, i) => i).sort((a, b) => raw[b] - raw[a]);
  const lead = raw[order[0]] - raw[order[1]];
  if (lead > 0) {
    weighted[order[0]] += AP_LEAPFROG_WEIGHT * spread * Math.tanh(lead / spread);
  }
  const wsum = weighted.reduce((a, b) => a + b, 0);
  if (wsum <= 0) return identity();
  const rawSum = raw.reduce((a, b) => a + b, 0);
  const scaled = weighted.map((w) => w * (rawSum / wsum));
  const rounded = roundPreservingTotal(scaled, grand);
  return Object.fromEntries(names.map((n, i) => [n, rounded[i]]));
}

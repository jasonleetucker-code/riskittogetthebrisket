// Join KeepTradeCut import entries onto board rows.
//
// The backend (POST /api/trade/import-ktc) resolves KTC playerIDs to KTC's own
// names and positions; this module only decides WHICH board row each one is.
// Pure — no React, no fetch — so the join is unit-testable.
//
// Ladder per entry: exact name -> case-insensitive -> normalized (punctuation,
// whitespace, generational suffix) -> pick-label resolver supplied by the
// caller.  The first rung with any candidate wins.  When that rung has several
// rows sharing the name (an offensive player and a defender, say), the row
// whose position matches KTC's stated position is preferred; if that still
// leaves a choice, the first row is used AND the name is reported in
// `ambiguous`, never silently guessed.

export function normalizeKtcName(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[.']/g, "")
    .replace(/\s+/g, " ")
    .replace(/\s+(jr|sr|ii|iii|iv|v)$/i, "")
    .trim();
}

function pushTo(map, key, row) {
  const bucket = map.get(key);
  if (bucket) bucket.push(row);
  else map.set(key, [row]);
}

export function buildKtcNameIndex(rows) {
  const exact = new Map();
  const lower = new Map();
  const norm = new Map();
  for (const r of rows || []) {
    if (!r?.name) continue;
    pushTo(exact, r.name, r);
    pushTo(lower, r.name.toLowerCase(), r);
    pushTo(norm, normalizeKtcName(r.name), r);
  }
  return { exact, lower, norm };
}

function choose(candidates, ktcPosition) {
  if (candidates.length === 1) return { row: candidates[0], ambiguous: false };
  const pos = String(ktcPosition || "").toUpperCase();
  const samePos = pos
    ? candidates.filter((r) => String(r?.pos || "").toUpperCase() === pos)
    : [];
  if (samePos.length === 1) return { row: samePos[0], ambiguous: false };
  const pool = samePos.length ? samePos : candidates;
  return { row: pool[0], ambiguous: true };
}

export function resolveKtcEntries(entries, index, { resolvePick } = {}) {
  const found = [];
  const missing = [];
  const ambiguous = [];
  for (const entry of entries || []) {
    const name = String(entry?.name || "");
    const candidates =
      index.exact.get(name) ||
      index.lower.get(name.toLowerCase()) ||
      index.norm.get(normalizeKtcName(name)) ||
      null;
    let row = null;
    if (candidates && candidates.length) {
      const picked = choose(candidates, entry?.position);
      row = picked.row;
      if (picked.ambiguous) ambiguous.push(name);
    } else if (typeof resolvePick === "function") {
      row = resolvePick(name) || null;
    }
    if (row) found.push(row);
    else missing.push(name);
  }
  return { found, missing, ambiguous };
}

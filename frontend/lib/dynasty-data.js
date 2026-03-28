const OFFENSE = new Set(["QB", "RB", "WR", "TE"]);
const IDP = new Set(["DL", "DE", "DT", "LB", "DB", "CB", "S", "EDGE"]);

export function normalizePos(pos) {
  const p = String(pos || "").toUpperCase();
  if (["DE", "DT", "EDGE", "NT"].includes(p)) return "DL";
  if (["CB", "S", "FS", "SS"].includes(p)) return "DB";
  if (["OLB", "ILB"].includes(p)) return "LB";
  return p;
}

export function classifyPos(pos) {
  const p = normalizePos(pos);
  if (OFFENSE.has(p)) return "offense";
  if (IDP.has(p)) return "idp";
  if (p === "PICK") return "pick";
  return "other";
}

export function inferValueBundle(player = {}) {
  const raw = Number(player._rawComposite ?? player._rawMarketValue ?? player._composite ?? 0) || 0;
  const scoring = Number(player._scoringAdjusted ?? raw) || raw;
  const scarcity = Number(player._scarcityAdjusted ?? scoring) || scoring;
  // Prefer 1–9999 display value; fall back to internal calibrated value
  const display = Number(player._canonicalDisplayValue ?? 0) || 0;
  const internal = Number(player._finalAdjusted ?? player._leagueAdjusted ?? scarcity) || scarcity;
  const full = display || internal;
  return {
    raw: Math.round(raw),
    scoring: Math.round(scoring),
    scarcity: Math.round(scarcity),
    full: Math.round(full),
  };
}

export function getSiteKeys(data) {
  const sites = Array.isArray(data?.sites) ? data.sites : [];
  return sites.map((s) => String(s?.key || "")).filter(Boolean);
}

// Site weights for consensus rank (mirrors scraper SITE_WEIGHTS).
const SITE_WEIGHTS = {
  ktc: 1.3, fantasyCalc: 1.0, dynastyDaddy: 1.0,
  draftSharks: 0.9, fantasyPros: 0.8, yahoo: 0.8,
  dynastyNerds: 0.8, idpTradeCalc: 1.0,
  dlf: 0.8, dlfDynasty: 0.8, dlfRedraft: 0.7, dlfBestBall: 0.7,
  pff: 0.7, fantasyProsIdp: 0.7, flock: 0.8,
};

/**
 * Compute a decimal consensus rank for each row from per-site values.
 * For each site, ranks rows by that site's value (desc), then blends
 * per-site ranks via weighted 70% median / 30% mean.
 */
function computeConsensusRanks(rows) {
  // Collect all site keys that have meaningful data
  const siteCounts = {};
  for (const row of rows) {
    for (const [key, val] of Object.entries(row.canonicalSites || {})) {
      if (Number.isFinite(Number(val)) && Number(val) > 0) {
        siteCounts[key] = (siteCounts[key] || 0) + 1;
      }
    }
  }
  // Only use sites with at least 20 players to avoid sparse-data noise
  const activeSites = Object.keys(siteCounts).filter((k) => siteCounts[k] >= 20);
  if (activeSites.length === 0) return;

  // For each site, sort rows and assign ranks
  const siteRanks = {}; // siteRanks[siteName] = Map<rowName, rank>
  for (const site of activeSites) {
    const withVal = rows
      .filter((r) => {
        const v = Number(r.canonicalSites?.[site]);
        return Number.isFinite(v) && v > 0;
      })
      .sort((a, b) => Number(b.canonicalSites[site]) - Number(a.canonicalSites[site]));

    const rankMap = new Map();
    for (let i = 0; i < withVal.length; i++) {
      rankMap.set(withVal[i].name, i + 1);
    }
    siteRanks[site] = rankMap;
  }

  // For each row, compute consensus rank from per-site ranks
  for (const row of rows) {
    const ranks = [];
    const weights = [];
    for (const site of activeSites) {
      const rank = siteRanks[site]?.get(row.name);
      if (rank != null) {
        ranks.push(rank);
        weights.push(SITE_WEIGHTS[site] || 0.8);
      }
    }
    if (ranks.length < 1) continue;

    // Weighted mean
    let wSum = 0, wTotal = 0;
    for (let i = 0; i < ranks.length; i++) {
      wSum += ranks[i] * weights[i];
      wTotal += weights[i];
    }
    const wMean = wSum / wTotal;

    // Median
    const sorted = [...ranks].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 === 0
      ? (sorted[mid - 1] + sorted[mid]) / 2
      : sorted[mid];

    // Blend: 70% median, 30% weighted mean
    row.computedConsensusRank = Math.round((0.7 * median + 0.3 * wMean) * 10) / 10;
  }
}

export function buildRows(data) {
  const players = data?.players || {};
  const playersArray = Array.isArray(data?.playersArray) ? data.playersArray : [];
  const posMap = data?.sleeper?.positions || {};
  const rows = [];

  if (playersArray.length) {
    for (const player of playersArray) {
      if (!player || typeof player !== "object") continue;
      const name = String(player.displayName || player.canonicalName || "").trim();
      if (!name) continue;
      const pos = normalizePos(player.position || "");
      if (pos === "K") continue;

      // Prefer 1–9999 display value; fall back to internal calibrated value
      const displayVal = Number(player?.values?.displayValue ?? 0) || 0;
      const internalVal = Number(
        player?.values?.finalAdjusted ?? player?.values?.overall ?? player?.values?.scarcityAdjusted ?? 0
      ) || 0;
      const values = {
        raw: Number(player?.values?.rawComposite ?? 0) || 0,
        scoring: Number(player?.values?.scoringAdjusted ?? player?.values?.rawComposite ?? 0) || 0,
        scarcity: Number(
          player?.values?.scarcityAdjusted ?? player?.values?.scoringAdjusted ?? player?.values?.rawComposite ?? 0
        ) || 0,
        full: displayVal || internalVal,
      };

      const canonicalSites =
        player.canonicalSiteValues && typeof player.canonicalSiteValues === "object"
          ? player.canonicalSiteValues
          : {};

      rows.push({
        name,
        pos: pos || "?",
        assetClass: String(player.assetClass || classifyPos(pos || "?")),
        values: {
          raw: Math.round(values.raw),
          scoring: Math.round(values.scoring),
          scarcity: Math.round(values.scarcity),
          full: Math.round(values.full),
        },
        siteCount: Number(player.sourceCount || 0),
        confidence: Number(player.marketConfidence ?? 0),
        marketLabel: "",
        canonicalSites,
        canonicalConsensusRank: Number(player.canonicalConsensusRank) || null,
        canonicalTierId: Number(player.canonicalTierId) || null,
        raw: player,
      });
    }

    rows.sort((a, b) => b.values.full - a.values.full);
    rows.forEach((r, i) => {
      r.rank = i + 1;
    });
    computeConsensusRanks(rows);
    return rows;
  }

  for (const [name, player] of Object.entries(players)) {
    if (!player || typeof player !== "object") continue;
    const isPick = /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i.test(name) || /^20\d{2}\s+pick/i.test(name);
    const pos = isPick ? "PICK" : normalizePos(posMap[name] || player.position || "");
    if (pos === "K") continue;

    const values = inferValueBundle(player);
    const canonicalSites = player._canonicalSiteValues && typeof player._canonicalSiteValues === "object" ? player._canonicalSiteValues : {};

    rows.push({
      name,
      pos: pos || "?",
      assetClass: classifyPos(pos || "?"),
      values,
      siteCount: Number(player._sites || 0),
      confidence: Number(player._marketReliabilityScore ?? 0),
      marketLabel: String(player._marketReliabilityLabel || ""),
      canonicalSites,
      canonicalConsensusRank: Number(player._canonicalConsensusRank) || null,
      canonicalTierId: Number(player._canonicalTierId) || null,
      raw: player,
    });
  }

  rows.sort((a, b) => b.values.full - a.values.full);
  rows.forEach((r, i) => {
    r.rank = i + 1;
  });
  computeConsensusRanks(rows);
  return rows;
}

export async function fetchDynastyData() {
  const res = await fetch("/api/dynasty-data", { cache: "no-store" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to load dynasty data: ${res.status} ${txt}`);
  }
  return res.json();
}

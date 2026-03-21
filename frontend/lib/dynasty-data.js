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
  const bundle = player.valueBundle && typeof player.valueBundle === "object" ? player.valueBundle : {};
  const raw = Number(bundle.rawValue ?? player._rawComposite ?? player._rawMarketValue ?? player._composite ?? 0) || 0;
  const scoring = Number(bundle.scoringAdjustedValue ?? player._scoringAdjusted ?? raw) || raw;
  const scarcity = Number(bundle.scarcityAdjustedValue ?? player._scarcityAdjusted ?? scoring) || scoring;
  const bestBall = Number(bundle.bestBallAdjustedValue ?? player._bestBallAdjusted ?? scarcity) || scarcity;
  const full = Number(bundle.fullValue ?? player._finalAdjusted ?? player._leagueAdjusted ?? bestBall) || bestBall;
  return {
    raw: Math.round(raw),
    scoring: Math.round(scoring),
    scarcity: Math.round(scarcity),
    bestBall: Math.round(bestBall),
    full: Math.round(full),
  };
}

function compactCanonicalSites(rawSites) {
  if (!rawSites || typeof rawSites !== "object") return {};
  const out = {};
  for (const [key, value] of Object.entries(rawSites)) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) continue;
    out[key] = Math.round(num);
  }
  return out;
}

function sourceCoverageRatio(sourceCoverage) {
  if (!sourceCoverage || typeof sourceCoverage !== "object") return null;
  const ratio = Number(sourceCoverage.ratio);
  return Number.isFinite(ratio) ? ratio : null;
}

function resolveGuardrails(playerLike) {
  const g = playerLike?.valueGuardrails;
  if (g && typeof g === "object") return g;
  const fromBundle = playerLike?.valueBundle?.guardrails;
  if (fromBundle && typeof fromBundle === "object") return fromBundle;
  return {};
}

function isFinalAuthorityQuarantined(playerLike) {
  const guardrails = resolveGuardrails(playerLike);
  if (guardrails && guardrails.quarantined === true) return true;
  const tags = Array.isArray(playerLike?.adjustmentTags)
    ? playerLike.adjustmentTags
    : (Array.isArray(playerLike?.valueBundle?.adjustmentTags) ? playerLike.valueBundle.adjustmentTags : []);
  return tags.includes("quarantined_from_final_authority");
}

function buildSearchBlob({ name, pos, team, assetClass }) {
  return [
    String(name || "").toLowerCase(),
    String(pos || "").toLowerCase(),
    String(team || "").toLowerCase(),
    String(assetClass || "").toLowerCase(),
  ]
    .filter(Boolean)
    .join(" ");
}

export function getSiteKeys(data) {
  const sites = Array.isArray(data?.sites) ? data.sites : [];
  return sites.map((s) => String(s?.key || "")).filter(Boolean);
}

export function buildRows(data, opts = {}) {
  const includeRaw = opts.includeRaw !== false;
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
      const assetClass = String(player.assetClass || classifyPos(pos || "?"));
      if (assetClass !== "pick" && isFinalAuthorityQuarantined(player)) continue;

      const values = {
        raw: Number(player?.valueBundle?.rawValue ?? player?.values?.rawComposite ?? 0) || 0,
        scoring: Number(player?.valueBundle?.scoringAdjustedValue ?? player?.values?.scoringAdjusted ?? player?.values?.rawComposite ?? 0) || 0,
        scarcity: Number(
          player?.valueBundle?.scarcityAdjustedValue ??
          player?.values?.scarcityAdjusted ??
          player?.values?.scoringAdjusted ??
          player?.values?.rawComposite ??
          0
        ) || 0,
        bestBall: Number(
          player?.valueBundle?.bestBallAdjustedValue ??
          player?.values?.bestBallAdjusted ??
          player?.values?.scarcityAdjusted ??
          player?.values?.scoringAdjusted ??
          player?.values?.rawComposite ??
          0
        ) || 0,
        full: Number(
          player?.valueBundle?.fullValue ??
          player?.values?.finalAdjusted ??
          player?.values?.overall ??
          player?.values?.bestBallAdjusted ??
          player?.values?.scarcityAdjusted ??
          0
        ) || 0,
      };

      const canonicalSites =
        player.canonicalSiteValues && typeof player.canonicalSiteValues === "object"
          ? player.canonicalSiteValues
          : {};
      const row = {
        name,
        searchName: name.toLowerCase(),
        pos: pos || "?",
        team: String(player.team || "").trim() || null,
        assetClass,
        values: {
          raw: Math.round(values.raw),
          scoring: Math.round(values.scoring),
          scarcity: Math.round(values.scarcity),
          bestBall: Math.round(values.bestBall),
          full: Math.round(values.full),
        },
        siteCount: Number(
          player?.sourceCoverage?.count ??
          player?.valueBundle?.sourceCoverage?.count ??
          player.sourceCount ??
          0
        ),
        confidence: Number(player?.confidence ?? player?.valueBundle?.confidence ?? player.marketConfidence ?? 0),
        sourceCoverage:
          player?.sourceCoverage && typeof player.sourceCoverage === "object"
            ? player.sourceCoverage
            : (player?.valueBundle?.sourceCoverage ?? null),
        sourceCoverageRatio: sourceCoverageRatio(player?.sourceCoverage ?? player?.valueBundle?.sourceCoverage ?? null),
        isRookie: Boolean(player?.rookie || player?._isRookie || player?._formatFitRookie),
        playerId: String(player?.playerId || "").trim() || null,
        adjustmentTags: Array.isArray(player?.adjustmentTags)
          ? player.adjustmentTags
          : (Array.isArray(player?.valueBundle?.adjustmentTags) ? player.valueBundle.adjustmentTags : []),
        valueGuardrails: resolveGuardrails(player),
        marketLabel: "",
        canonicalSites: compactCanonicalSites(canonicalSites),
      };
      row.searchBlob = buildSearchBlob({
        name,
        pos: row.pos,
        team: row.team,
        assetClass: row.assetClass,
      });
      if (includeRaw) row.raw = player;
      rows.push(row);
    }

    rows.sort((a, b) => b.values.full - a.values.full);
    rows.forEach((r, i) => {
      r.rank = i + 1;
    });
    return rows;
  }

  for (const [name, player] of Object.entries(players)) {
    if (!player || typeof player !== "object") continue;
    const isPick = /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i.test(name) || /^20\d{2}\s+pick/i.test(name);
    const pos = isPick ? "PICK" : normalizePos(posMap[name] || player.position || "");
    if (pos === "K") continue;
    const assetClass = classifyPos(pos || "?");
    if (assetClass !== "pick" && isFinalAuthorityQuarantined(player)) continue;

    const values = inferValueBundle(player);
    const canonicalSites = player._canonicalSiteValues && typeof player._canonicalSiteValues === "object" ? player._canonicalSiteValues : {};
    const sourceCoverage =
      player.valueBundle?.sourceCoverage && typeof player.valueBundle.sourceCoverage === "object"
        ? player.valueBundle.sourceCoverage
        : null;
    const row = {
      name,
      searchName: name.toLowerCase(),
      pos: pos || "?",
        team: String(player.team || "").trim() || null,
        assetClass,
      values,
      siteCount: Number(player._sites || 0),
      confidence: Number(player.valueBundle?.confidence ?? player._marketReliabilityScore ?? 0),
      sourceCoverage,
      sourceCoverageRatio: sourceCoverageRatio(sourceCoverage),
      isRookie: Boolean(player._formatFitRookie || player._isRookie),
      playerId: String(player._sleeperId || "").trim() || null,
      adjustmentTags: Array.isArray(player.valueBundle?.adjustmentTags) ? player.valueBundle.adjustmentTags : [],
      valueGuardrails: resolveGuardrails(player),
      marketLabel: String(player._marketReliabilityLabel || ""),
      canonicalSites: compactCanonicalSites(canonicalSites),
    };
    row.searchBlob = buildSearchBlob({
      name,
      pos: row.pos,
      team: row.team,
      assetClass: row.assetClass,
    });
    if (includeRaw) row.raw = player;
    rows.push(row);
  }

  rows.sort((a, b) => b.values.full - a.values.full);
  rows.forEach((r, i) => {
    r.rank = i + 1;
  });
  return rows;
}

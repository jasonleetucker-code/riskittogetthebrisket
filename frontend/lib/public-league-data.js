// Public league data fetcher — ISOLATED from the private /api/data
// pipeline.
//
// The /league page must never hydrate from the private canonical
// contract (buildRows, useDynastyData, siteOverrides, etc.).  Every
// fetch here targets /api/public/league* and returns the public
// contract shape defined in src/public_league/public_contract.py:
//
//   {
//     contractVersion: "public-league/YYYY-MM-DD.vN",
//     league: {
//       rootLeagueId, leagueName, seasonsCovered, leagueIds,
//       currentLeagueId, generatedAt, managers: [ ... ]
//     },
//     sections: {
//       history, rivalries, awards, records, franchise, activity,
//       draft, weekly, superlatives, archives
//     },
//     sectionKeys: [ ... ]
//   }
//
// Or for a single section request:
//
//   { contractVersion, league, section, data }
//
// Any caller importing anything from frontend/lib/dynasty-data.js or
// frontend/components/useDynastyData is a privacy leak in the public
// /league flow — the isolation is architectural, not just a comment.

export const PUBLIC_SECTION_KEYS = Object.freeze([
  "overview",
  "history",
  "rivalries",
  "awards",
  "records",
  "franchise",
  "activity",
  "draft",
  "weekly",
  "superlatives",
  "archives",
]);

async function _getJson(url) {
  const resp = await fetch(url, {
    method: "GET",
    credentials: "omit",
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) {
    throw new Error(`Public league fetch failed (${resp.status}) for ${url}`);
  }
  return resp.json();
}

export async function fetchPublicLeague({ refresh } = {}) {
  const qs = refresh ? "?refresh=1" : "";
  return _getJson(`/api/public/league${qs}`);
}

export async function fetchPublicSection(section, { owner, refresh } = {}) {
  if (!PUBLIC_SECTION_KEYS.includes(section)) {
    throw new Error(`Unknown public section: ${section}`);
  }
  const params = new URLSearchParams();
  if (owner) params.set("owner", owner);
  if (refresh) params.set("refresh", "1");
  const qs = params.toString();
  return _getJson(`/api/public/league/${section}${qs ? `?${qs}` : ""}`);
}

export async function fetchPublicMatchup(season, week, matchupId, { refresh } = {}) {
  const qs = refresh ? "?refresh=1" : "";
  return _getJson(
    `/api/public/league/matchup/${encodeURIComponent(season)}/${encodeURIComponent(week)}/${encodeURIComponent(matchupId)}${qs}`,
  );
}

export async function fetchPublicPlayer(playerId, { refresh } = {}) {
  const qs = refresh ? "?refresh=1" : "";
  return _getJson(
    `/api/public/league/player/${encodeURIComponent(playerId)}${qs}`,
  );
}

export async function fetchPublicPlayersIndex({ refresh } = {}) {
  const qs = refresh ? "?refresh=1" : "";
  return _getJson(`/api/public/league/players${qs}`);
}

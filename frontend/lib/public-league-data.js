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
  "luck",
  "streaks",
  "conduct",
  "matchupPreview",
  "weeklyRecap",
]);

// Transient reverse-proxy / gateway statuses.  A cold-start or forced
// snapshot rebuild on the backend can momentarily leave nginx without a
// ready upstream, which surfaces to the client as a 502/504.  These are
// self-healing within a second or two, so we retry with a short backoff
// instead of nuking the whole /league page on a single blip.  Application
// statuses like 503 ("data unavailable") and 4xx are NOT retried — those
// are deliberate backend responses, not gateway flaps.
const _TRANSIENT_GATEWAY_STATUSES = new Set([502, 504]);
const _MAX_FETCH_ATTEMPTS = 3;

function _sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function _getJson(url) {
  let lastErr;
  for (let attempt = 1; attempt <= _MAX_FETCH_ATTEMPTS; attempt += 1) {
    let resp;
    try {
      resp = await fetch(url, {
        method: "GET",
        credentials: "omit",
        headers: { Accept: "application/json" },
      });
    } catch (err) {
      // Network-level failure (connection reset mid-rebuild, etc.) — retry.
      lastErr = err;
      if (attempt < _MAX_FETCH_ATTEMPTS) {
        await _sleep(300 * attempt);
        continue;
      }
      throw err;
    }
    if (resp.ok) {
      return resp.json();
    }
    lastErr = new Error(
      `Public league fetch failed (${resp.status}) for ${url}`,
    );
    if (
      _TRANSIENT_GATEWAY_STATUSES.has(resp.status) &&
      attempt < _MAX_FETCH_ATTEMPTS
    ) {
      await _sleep(300 * attempt);
      continue;
    }
    throw lastErr;
  }
  throw lastErr;
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

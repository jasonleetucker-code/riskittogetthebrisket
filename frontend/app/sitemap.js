// Dynamic sitemap.xml for the public site.
//
// Lists every public URL Google / Bing can crawl.  Pulls the live
// manager + matchup + player indexes from the backend so every
// deep-linked page (franchise, rivalry, matchup recap, player
// journey) gets its own entry.  Falls back to just the static routes
// if the backend gives no usable answer at build time.
//
// That fallback used to cover only an UNREACHABLE backend.  The three
// fetches below ran unbounded, so a backend that accepted connections
// and never answered — the 2026-08-12 file-descriptor exhaustion — left
// them pending rather than falling back, three times in sequence.  This
// route stays statically generated (`revalidate` 10 m); what changed is
// that each fetch now has a bounded budget, so "no usable answer"
// includes silence and the documented fallback actually happens.
//
// Deliberately NOT given the `connection()` treatment that
// `app/league/page.jsx` got: a sitemap is legitimately static, and
// forcing it to render per request to fix a timeout would be a product
// change dressed as a repair.  A build during an outage emits the static
// routes only, for one revalidate window.

import { fetchBackendJson } from "../lib/server-backend.js";
import { isPublicPath } from "../lib/public-routes.js";

function _origin() {
  return (
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.PUBLIC_SITE_URL ||
    "https://chaseupside.com"
  ).replace(/\/$/, "");
}

async function _fetchJson(path) {
  return fetchBackendJson(path, { revalidate: 600 });
}

export default async function sitemap() {
  const origin = _origin();
  const now = new Date();

  // Static public routes.
  //
  // FILTERED through `isPublicPath`, the one predicate that answers
  // "is this reachable without a session". `public-routes.js` says it
  // exists because middleware, the app shell and robots.txt used to
  // disagree — but the sitemap was a FOURTH consumer that was never
  // wired to it, and it drifted exactly the way the other three had.
  //
  // Measured on production 2026-09-05 (W1-13): `/trades` was listed
  // here while `public-routes.js` declares it private and the page
  // redirects an anonymous visitor to `/login?next=%2Ftrades`. Nothing
  // leaked — `robots.txt` serves `Disallow: /` and only allows `/`,
  // `/login` and `/league` — but a sitemap is a positive assertion that
  // a URL is worth indexing, it is submitted to search engines, and it
  // contradicted robots.txt on the same host.
  //
  // Filtering rather than deleting the entry: a hand-edited list drifts
  // again the next time a route changes sides. The query-string entries
  // are checked on their pathname, which is what the predicate takes.
  const staticEntries = [
    "/",
    "/trades",
    "/draft-capital",
    "/league",
    "/league?tab=matchupPreview",
    "/league?tab=power",
    "/league?tab=luck",
    "/league?tab=streaks",
    "/league?tab=weeklyRecap",
    "/league?tab=history",
    "/league?tab=rivalries",
    "/league?tab=awards",
    "/league?tab=records",
    "/league?tab=franchise",
    "/league?tab=activity",
    "/league?tab=draft",
    "/league?tab=weekly",
    "/league?tab=superlatives",
    "/league?tab=archives",
  ]
    .filter((path) => isPublicPath(path.split("?")[0]))
    .map((path) => ({
      url: `${origin}${path}`,
      lastModified: now,
      changeFrequency: "daily",
      priority: path === "/" ? 1.0 : 0.7,
    }));

  // Franchise entries — one per manager.
  const leaguePayload = await _fetchJson("/api/public/league");
  const managers = leaguePayload?.league?.managers || [];
  const franchiseEntries = managers.map((m) => ({
    url: `${origin}/league/franchise/${encodeURIComponent(m.ownerId)}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  // Rivalry entries — one per pair.
  const rivalries = leaguePayload?.sections?.rivalries?.rivalries || [];
  const rivalryEntries = rivalries.map((r) => {
    const [a, b] = r.ownerIds;
    return {
      url: `${origin}/league/rivalry/${encodeURIComponent(`${a}-vs-${b}`)}`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.7,
    };
  });

  // Matchup recap entries — one per scored matchup pair.
  const matchupsPayload = await _fetchJson("/api/public/league/matchups");
  const matchups = matchupsPayload?.matchups || [];
  const matchupEntries = matchups.map((m) => ({
    url: `${origin}/league/weekly/${encodeURIComponent(m.season)}/${encodeURIComponent(m.week)}/${encodeURIComponent(m.matchupId)}`,
    lastModified: now,
    changeFrequency: "yearly",
    priority: 0.5,
  }));

  // Weekly-recap entries — one per scored week across the snapshot.
  // Dedupe by (season, week) since the matchup index repeats it.
  const recapSeen = new Set();
  const recapEntries = [];
  for (const m of matchups) {
    const key = `${m.season}:${m.week}`;
    if (recapSeen.has(key)) continue;
    recapSeen.add(key);
    recapEntries.push({
      url: `${origin}/league/week/${encodeURIComponent(m.season)}/${encodeURIComponent(m.week)}`,
      lastModified: now,
      changeFrequency: "yearly",
      priority: 0.6,
    });
  }

  // Player-journey entries — one per player with activity.  Capped at
  // 2,000 to keep the sitemap under Google's 50k-URL / 50 MB limit.
  const playersPayload = await _fetchJson("/api/public/league/players");
  const players = (playersPayload?.players || []).filter((p) => p.playerName);
  const playerEntries = players.slice(0, 2000).map((p) => ({
    url: `${origin}/league/player/${encodeURIComponent(p.playerId)}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.4,
  }));

  return [
    ...staticEntries,
    ...franchiseEntries,
    ...rivalryEntries,
    ...matchupEntries,
    ...recapEntries,
    ...playerEntries,
  ];
}

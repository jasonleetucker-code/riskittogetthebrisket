// Dynamic sitemap.xml for the public site.
//
// Lists every public URL Google / Bing can crawl.  Pulls the live
// manager + matchup + player indexes from the backend so every
// deep-linked page (franchise, rivalry, matchup recap, player
// journey) gets its own entry.  Falls back to just the static routes
// if the backend is unreachable at build time.

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

function _origin() {
  return (
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.PUBLIC_SITE_URL ||
    "https://riskittogetthebrisket.org"
  ).replace(/\/$/, "");
}

async function _fetchJson(path) {
  try {
    const res = await fetch(`${_backend()}${path}`, {
      next: { revalidate: 600 },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function sitemap() {
  const origin = _origin();
  const now = new Date();

  // Static public routes.
  const staticEntries = [
    "/",
    "/trades",
    "/draft-capital",
    "/league",
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
  ].map((path) => ({
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
    ...playerEntries,
  ];
}

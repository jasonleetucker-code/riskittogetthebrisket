// Server component for the public /league route.
//
// Fetches the public contract on the server so the first paint ships
// with real data — no "Loading league data..." flash.  Also produces
// OG / Twitter metadata using the live contract, so shared links
// preview a proper title + description.
//
// The actual tabbed UI lives in ./LeagueClient.jsx (client component).
// We pass ``initialContract`` + ``initialTab`` through as props.
//
// Isolation contract (see LeagueClient.jsx): nothing here touches
// /api/data, useDynastyData, or any private module — only the public
// /api/public/league endpoint.

import LeagueClient from "./LeagueClient.jsx";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchContract() {
  const url = `${_backend()}/api/public/league`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || typeof data !== "object" || !data.sections || !data.league) {
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

export async function generateMetadata() {
  const data = await fetchContract();
  if (!data) {
    return {
      title: "Risk It To Get The Brisket — public league",
      description: "Public league home for the Brisket dynasty league.",
    };
  }
  const league = data.league || {};
  const overview = data.sections?.overview || {};
  const name = league.leagueName || "Brisket League";
  const range = overview.seasonRangeLabel || (league.seasonsCovered || []).join("–");
  const champ = overview.currentChampion;
  const decorated = overview.mostDecoratedFranchise;
  const rivalry = overview.featuredRivalry;
  const parts = [];
  if (champ) parts.push(`Champ: ${champ.displayName}`);
  if (decorated) parts.push(`Top franchise: ${decorated.displayName}`);
  if (rivalry && rivalry.displayNames?.length === 2) {
    parts.push(`Rivalry: ${rivalry.displayNames[0]} vs ${rivalry.displayNames[1]}`);
  }
  const description = parts.length
    ? `${range} · ${parts.join(" · ")}`
    : `Public dynasty league home (${range || "last 2 seasons"}).`;
  const title = `${name} · ${range || "2-season dynasty view"}`;
  return {
    title,
    description,
    openGraph: { title, description, type: "website", siteName: name },
    twitter: { card: "summary", title, description },
  };
}

export default async function LeagueRoute({ searchParams }) {
  const sp = (await searchParams) || {};
  const rawTab = typeof sp.tab === "string" ? sp.tab : Array.isArray(sp.tab) ? sp.tab[0] : "overview";
  const initialContract = await fetchContract();
  return (
    <LeagueClient initialContract={initialContract} initialTab={rawTab} />
  );
}

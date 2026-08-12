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

import { cache } from "react";
import { connection } from "next/server";
import LeagueClient from "./LeagueClient.jsx";
import { fetchBackendJson } from "../../lib/server-backend.js";
import { DEFAULT_TAB, normalizeTabKey, sectionForTab } from "./tabs.js";

// Fetch ONE public-contract section.  Shape: {contractVersion, league,
// section, data} — every section response carries the ``league`` block,
// which is why the page never needs the aggregate endpoint.
//
// Why per-section instead of the whole contract:
//
//   The aggregate ``/api/public/league`` is 2.01 MB of JSON across 17
//   sections.  This page renders ONE tab at a time, and the landing tab
//   (`overview`) is 7.6 KB of it.  The rest was fetched, parsed, and —
//   because ``initialContract`` is a prop on a client component —
//   serialized into the RSC flight payload and shipped to every
//   visitor, making the /league document 2.38 MB.  Two sections in it
//   (`weeklyRecap` 378 KB, `matchupPreview` 11 KB) are not read by this
//   page AT ALL: the AI-article tabs replaced those views and fetch
//   their own data.
//
//   It also could not be cached on the way in.  Next's Data Cache
//   refuses entries over 2 MB, so ``revalidate: 60`` was silently inert
//   on the aggregate and every render re-fetched and re-parsed the full
//   payload.  At 7.6 KB a section entry caches normally and the
//   revalidate window does what it says.
//
// Cache: Next Data Cache, keyed by the section URL, revalidate 60s.
// Sections are derived from one backend snapshot that the backend
// itself refreshes on its own schedule, so a stale read is at worst a
// minute-old view of an already-eventually-consistent public league
// page — no private data, no trade math, nothing a user acts on.  Tabs
// opened later fetch their own sections, so a long-lived tab CAN show
// two sections built from snapshots up to a minute apart; they are
// independent read-only views (Records vs Archives), never two halves
// of one number.
//
// React cache(): ``generateMetadata`` and the page body both await the
// overview section during one render pass, and de-duping that is the
// difference between one backend call and two.
//
// BUILD INDEPENDENCE (2026-08-12 incident).  `await connection()` is the
// first thing here, and it is load-bearing rather than decorative.
//
// This route is already dynamic — the production build stamps it `ƒ`,
// server-rendered on demand — but Next still EVALUATES it during
// `next build` to discover that, and `generateMetadata` runs in the same
// pass.  So the build issued this fetch.  With the backend accepting
// connections and never answering, the render hung, Next killed it at
// its 60 s page-generation limit, retried twice, and failed the build:
//
//     Failed to build /league/page: /league after 3 attempts.
//     Export encountered an error on /league/page: /league, exiting the build.
//
// `connection()` aborts the render at THIS line during prerendering, so
// the fetch is never issued and the build cannot depend on a live
// FastAPI process. At request time it resolves immediately and costs
// nothing. That is the mechanism, not a longer timeout — the previous
// note in this file assumed a dynamic route was already exempt from the
// build, and it is not.
//
// Placed inside `fetchSection` rather than at the top of the page and
// again in `generateMetadata`: this is the single choke point for every
// backend call on this route, so a future caller cannot forget it.
//
// The fetch itself is bounded by `lib/server-backend.js` (8 s), which is
// the separate, request-time half of the same incident: a wedged backend
// must not hold a visitor's connection either.
const fetchSection = cache(async function fetchSection(section) {
  await connection();
  const data = await fetchBackendJson(`/api/public/league/${encodeURIComponent(section)}`, {
    revalidate: 60,
  });
  if (!data || typeof data !== "object" || !data.league) return null;
  return data;
});

export async function generateMetadata() {
  const data = await fetchSection("overview");
  if (!data) {
    return {
      title: "Risk It To Get The Brisket — public league",
      description: "Public league home for the dynasty league.",
    };
  }
  const league = data.league || {};
  const overview = data.data || {};
  const name = league.leagueName || "Chase Upside";
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
  // Default tab matches DEFAULT_TAB ("overview") — LeagueClient
  // validates the key against VALID_TABS so an unknown ?tab= value
  // falls back safely.
  const rawTab =
    typeof sp.tab === "string"
      ? sp.tab
      : Array.isArray(sp.tab)
        ? sp.tab[0]
        : DEFAULT_TAB;

  // ``overview`` is always fetched, not only for the overview tab: the
  // page header's season label reads it on every tab.  A deep link to
  // any other tab pulls that tab's section too, so the landing view is
  // still fully server-rendered — which is what keeps crawlers and
  // shared links seeing real content instead of a spinner.  Everything
  // else loads when the visitor actually opens it.
  //
  // ``archives`` is the one exception (2026-07-30), and it is a size
  // decision rather than a policy change.  At ~737 KB it is 8x the next
  // largest section; inlining it into the RSC flight payload took this
  // document from ~91 KB to ~960 KB, and that payload is what made
  // hydration slow enough to race (#662).  The client already fetches
  // sections it lacks — ``LeagueClient``'s lazy-section effect handles
  // archives on a tab switch today, with an in-flight guard — and
  // ``ArchivesSection`` is written for a null first render.  So SSR here
  // bought nothing but bytes.
  //
  // What is genuinely given up: a crawler following ``?tab=archives``
  // sees the shell rather than the table.  Archives is a waiver / draft /
  // trade log, not the shareable surface; ``overview``, which carries the
  // OG title and description, still server-renders on every tab.
  const landing = sectionForTab(normalizeTabKey(rawTab));
  const ssrSkip = new Set(["archives"]);
  const wanted =
    landing && landing !== "overview" && !ssrSkip.has(landing)
      ? ["overview", landing]
      : ["overview"];
  const payloads = await Promise.all(wanted.map((s) => fetchSection(s)));

  let league = null;
  let contractVersion = null;
  const sections = {};
  for (const payload of payloads) {
    if (!payload) continue;
    if (!league) league = payload.league;
    if (!contractVersion) contractVersion = payload.contractVersion;
    if (payload.section) sections[payload.section] = payload.data;
  }
  // Null (not a half-built object) when the backend gave us nothing —
  // LeagueClient's bootstrap path treats that as "fetch it yourself",
  // which is the behaviour that already existed for an SSR failure.
  const initialContract = league ? { contractVersion, league, sections } : null;

  return <LeagueClient initialContract={initialContract} initialTab={rawTab} />;
}

/**
 * Brisket Trade Advisor — the frontend never holds a value (design §8.6,
 * §11 group D frontend half).
 *
 * Source scans over every advisor module (and the hub files that mount it):
 *   - no import of the private pipeline / trade engine / session state;
 *   - no request to a private data path, never `credentials: "include"`;
 *   - no value-shaped field name read off a payload;
 *   - the picker publishes no list position (no aria-posinset/setsize, no
 *     <ol>), and no data-* attribute carries anything numeric about an asset;
 *   - the dev bridges refuse to run in production;
 *   - the hub's routing wiring (split server-rendered team step, static Overview, push for tab
 *     clicks, server-read bootstrap) stays in place.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

const ADVISOR_FILES = [
  "lib/trade-advisor.js",
  "lib/trade-advisor-client.js",
  "app/league/sections/trade-advisor-shell.jsx",
  "app/league/sections/trade-advisor.jsx",
  "app/league/sections/_advisor-team-panel.jsx",
  "app/league/sections/_advisor-asset-picker.jsx",
  "app/league/sections/_advisor-asset-sheet.jsx",
  "app/league/sections/_advisor-summary.jsx",
  "app/league/sections/_advisor-result.jsx",
  "components/ds/Combobox.jsx",
];

// Strip comments so prose that NAMES a forbidden thing (to forbid it) does
// not trip the scan.
function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("advisor modules stay outside the private pipeline", () => {
  const FORBIDDEN_IMPORTS = [
    /dynasty-data/,
    /useDynastyData/,
    /trade-logic/,
    /trade-assets/,
    /trade-war-room/,
    /league-analysis/,
    /edge-helpers/,
    /AppShell/,
    /useApp\b/,
    /fairness-bands/,
    /package-model/,
  ];
  it.each(ADVISOR_FILES)("%s imports nothing private", (rel) => {
    const imports = code(read(rel)).match(/^\s*import[\s\S]*?from\s+["'][^"']+["']/gm) || [];
    const dynamic = code(read(rel)).match(/import\(\s*["'][^"']+["']\s*\)/g) || [];
    for (const line of [...imports, ...dynamic]) {
      for (const re of FORBIDDEN_IMPORTS) expect(line, `${rel}: ${line}`).not.toMatch(re);
    }
  });

  it.each(ADVISOR_FILES)("%s requests no private data path and never sends credentials", (rel) => {
    const src = code(read(rel));
    for (const marker of ["/api/data", "/api/dynasty-data", "/api/trade/", "/api/rankings", 'credentials: "include"', "credentials:'include'"]) {
      expect(src.includes(marker), `${rel} contains ${marker}`).toBe(false);
    }
  });

  it.each(ADVISOR_FILES)("%s reads no value-shaped field", (rel) => {
    const src = code(read(rel));
    expect(src).not.toMatch(/\b(rankDerivedValue|displayValue|ktcValue|canonicalConsensusRank|vaAdjustedGap|whatWouldChange|objectiveValue|equity)\b/);
    expect(src).not.toMatch(/\.\s*(rank|score|gap|band|confidence|percentile)\b/);
    // `.value` only as a DOM input's value or a select/combobox OPTION's
    // value (a roster id / enum), never off a payload.
    for (const m of src.matchAll(/([\w\]\[]+)\.value\b/g)) {
      expect(m[1], `${rel}: ${m[0]}`).toMatch(/^(target|opt|o|options\[\w+\])$/);
    }
  });
});

describe("the picker publishes no position or numeric attribute", () => {
  it.each(ADVISOR_FILES.filter((f) => f.endsWith(".jsx")))("%s", (rel) => {
    const src = code(read(rel));
    expect(src).not.toMatch(/aria-posinset|aria-setsize|ariaPosinset|ariaSetsize/);
    expect(src).not.toMatch(/<ol\b/);
    const dataAttrs = src.match(/data-[a-z-]+=/g) || [];
    for (const attr of dataAttrs) {
      expect(["data-testid=", "data-tone=", "data-category=", "data-count="]).toContain(attr);
    }
  });
});

describe("dev bridges", () => {
  const BRIDGE = "app/api/public/league/trade-advisor/_bridge.js";
  it("refuse to run in production and forward no cookies or client-IP headers", () => {
    const src = code(read(BRIDGE));
    expect(src).toMatch(/process\.env\.NODE_ENV === "production"/);
    expect(src).not.toMatch(/cookie|x-forwarded-for|x-real-ip/i);
    expect(src).not.toMatch(/err\?\.message|err\.message/);
  });
  it.each([
    "app/api/public/league/trade-advisor/teams/route.js",
    "app/api/public/league/trade-advisor/teams/[rosterId]/assets/route.js",
    "app/api/public/league/trade-advisor/analyze/route.js",
  ])("%s goes through the bridge", (rel) => {
    expect(read(rel)).toMatch(/forwardAdvisor\(/);
  });
});

describe("hub routing wiring", () => {
  const client = code(read("app/league/LeagueClient.jsx"));
  const page = code(read("app/league/page.jsx"));
  it("the team step is its own server-rendered chunk; Overview stays static (as on main)", () => {
    // Flag off = main byte for byte: /league's page chunk carries no
    // advisor code (check-public-bundle-privacy.mjs asserts it on the
    // build), so the team step is a `ssr: true` dynamic import that only
    // renders while the advisor is served.
    expect(client).toMatch(
      /TradeAdvisorShell = dynamic\(\(\) => import\("\.\/sections\/trade-advisor-shell\.jsx"\), \{\s*ssr: true,\s*loading: sectionLoading,\s*\}\)/,
    );
    expect(client).not.toMatch(/import TradeAdvisorShell from/);
    // Overview: main's static import (same SSR markup, same bytes).
    expect(client).toMatch(/import OverviewSection from "\.\/sections\/overview\.jsx"/);
    expect(client).not.toMatch(/OverviewSection = (lazySection|dynamic)/);
    // The builder is never on the page chunk.
    expect(client).not.toMatch(/sections\/trade-advisor\.jsx/);
  });
  it("tab clicks push history entries only while the advisor is served; section selectors replace", () => {
    expect(client).toMatch(/router\.push\(href/);
    expect(client).toMatch(/if \(mode === "replace" \|\| !advisorAvailable\) router\.replace\(href/);
    expect(client).toMatch(/setActiveTab\("franchise", \{ owner \}, "replace"\)/);
    expect(client).toMatch(/setActiveTab\("weekly", \{ week \}, "replace"\)/);
    expect(client).toMatch(/setActiveTab\("draft", \{ owner \}, "replace"\)/);
  });
  it("the server reads the advisor bootstrap and classifies it before it becomes a prop", () => {
    // One owner of the read + classification (advisor-bootstrap.js).
    expect(page).toMatch(/from "\.\/advisor-bootstrap\.js"/);
    expect(page).not.toMatch(/fetchBackendResult/);
    expect(page).toMatch(/initialAdvisor=\{initialAdvisor\}/);
  });
  it("league back-links go through the flag-gated league-home href (8 links)", () => {
    // `/league` exactly as on main while the advisor is off or unconfirmed;
    // `/league?tab=overview` only once it is confirmed served.  The rule is
    // `leagueHomeHrefFor` (tabs.js); behaviour is pinned in
    // league-tab-sections.test.js.
    const serverFiles = [
      "app/league/rivalry/[pair]/page.jsx",
      "app/league/articles/[season]/[week]/page.jsx",
      "app/league/weekly/[season]/[week]/[matchup]/page.jsx",
      "app/league/franchise/[owner]/page.jsx",
      "app/league/player/[playerId]/page.jsx",
    ];
    const files = ["app/league/activity/ActivityClient.jsx", ...serverFiles];
    let count = 0;
    for (const f of files) {
      const src = read(f);
      expect(src, f).not.toMatch(/<Link href="\/league(\?tab=overview)?" /);
      count += (src.match(/<Link href=\{leagueHome\}/g) || []).length;
    }
    expect(count).toBe(8);
    // Every href is decided on the server — the activity page too, through
    // its server wrapper — so no browser teams request picks a back-link.
    for (const f of [...serverFiles, "app/league/activity/page.jsx"]) {
      expect(read(f), f).toMatch(/leagueHomeHref\(\)/);
    }
    expect(read("app/league/activity/ActivityClient.jsx")).not.toMatch(/trade-advisor-client|fetchAdvisorTeams/);
    const helper = code(read("app/league/advisor-bootstrap.js"));
    expect(helper).toMatch(/\/api\/public\/league\/trade-advisor\/teams/);
    expect(helper).toMatch(/classifyTeamsResult\(result\)/);
    expect(helper).not.toMatch(/connection\(/);
  });
  it("the landing button says 'Go to League Hub' only when the advisor is confirmed served", () => {
    expect(read("app/HomeClient.jsx")).toMatch(/advisorServed \? "Go to League Hub" : "League"/);
    expect(read("app/page.jsx")).toMatch(/advisorConfirmedServed\(\)/);
  });
});

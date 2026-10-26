import { describe, expect, it } from "vitest";

import nextConfig from "../next.config.mjs";
import { leagueTabHref } from "../app/league/tabs.js";

// The legacy `/draft-capital` link is a routing-layer redirect.  Next.js
// passes the incoming query string through to the destination, so
// `/draft-capital?year=2028` lands on `/league?tab=draft-capital&year=2028`
// (observed in the local browser check).  This pins the config half.
describe("legacy /draft-capital redirect", () => {
  it("routes /draft-capital to the league draft-capital tab, permanently", async () => {
    const rules = await nextConfig.redirects();
    const rule = rules.find((r) => r.source === "/draft-capital");
    expect(rule).toBeDefined();
    expect(rule.destination).toBe("/league?tab=draft-capital");
    expect(rule.permanent).toBe(true);
    // No `has`/`missing` matcher that could swallow ?year=.
    expect(rule.has).toBeUndefined();
    expect(rule.missing).toBeUndefined();
  });
});

describe("year param is scoped to the draft-capital tab", () => {
  it("leaving the tab with year:null drops ?year=", () => {
    const href = leagueTabHref("power", "tab=draft-capital&year=2028", { year: null });
    expect(href).not.toContain("year=");
  });
});

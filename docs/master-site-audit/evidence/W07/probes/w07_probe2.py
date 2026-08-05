"""W07 probe 2: unpriced-row display, valuation-mode persistence, export."""

import asyncio
import json
import os

from playwright.async_api import async_playwright

PAGES = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W07"
COOKIE = "589c8aa3f7904df681c9d58413523a4e"

SCRAPE = """
() => {
  const tables = Array.from(document.querySelectorAll('table'));
  let best = null, bestN = 0;
  for (const t of tables) {
    const n = t.querySelectorAll('tbody tr').length;
    if (n > bestN) { bestN = n; best = t; }
  }
  if (!best) return {headers: [], rows: []};
  return {
    headers: Array.from(best.querySelectorAll('thead th')).map(x=>x.innerText.trim()),
    rows: Array.from(best.querySelectorAll('tbody tr')).map(
      tr => Array.from(tr.querySelectorAll('td,th')).map(td=>td.innerText.trim()))
  };
}
"""


async def mk(pw):
    b = await pw.chromium.launch()
    ctx = await b.new_context(viewport={"width": 1600, "height": 1400})

    async def route(r):
        u = r.request.url
        if "/api/" in u and u.startswith(PAGES):
            await r.continue_(url=u.replace(PAGES, API))
        else:
            await r.continue_()

    await ctx.route("**/*", route)
    await ctx.add_cookies(
        [
            {
                "name": "jason_session",
                "value": COOKIE,
                "domain": "127.0.0.1",
                "path": "/",
            }
        ]
    )
    return b, ctx


async def open_rankings(ctx, settings):
    p = await ctx.new_page()
    await p.goto(PAGES + "/", wait_until="domcontentloaded")
    await p.evaluate("s => localStorage.setItem('next_settings_v2', JSON.stringify(s))", settings)
    await p.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
    await p.wait_for_selector("table tbody tr", timeout=45000)
    await p.wait_for_timeout(3000)
    return p


async def search_and_scrape(p, name):
    box = p.locator("input[type=search], input[placeholder*='earch' i]").first
    await box.fill("")
    await box.fill(name)
    await p.wait_for_timeout(1500)
    return await p.evaluate(SCRAPE)


async def main():
    out = {}
    base = {"valuationMode": "market", "siteWeights": {}}
    async with async_playwright() as pw:
        b, ctx = await mk(pw)
        p = await open_rankings(ctx, base)

        # A. unpriced players — do they render a fabricated rank?
        out["unpriced"] = {}
        for name in ["Austin Ekeler", "AJ Dillon", "Alexander Mattison", "Arian Smith"]:
            out["unpriced"][name] = await search_and_scrape(p, name)

        # B. priced control
        out["priced"] = {}
        for name in ["Josh Allen", "Drake London", "Trey Lance"]:
            out["priced"][name] = await search_and_scrape(p, name)

        # C. CSV export vs screen
        await search_and_scrape(p, "")
        screen = await p.evaluate(SCRAPE)
        out["screenBeforeExport"] = screen
        csv = await p.evaluate("""
          () => {
            const btns = Array.from(document.querySelectorAll('button,a'));
            return btns.map(b=>b.innerText.trim()).filter(Boolean);
          }
        """)
        out["buttons"] = csv
        await p.close()

        # D. valuation-mode persistence across navigation + reload
        adj = {"valuationMode": "leagueAdjusted", "siteWeights": {}}
        p2 = await open_rankings(ctx, adj)
        out["adjRankings"] = await p2.evaluate(SCRAPE)
        # navigate away and back within SPA
        await p2.goto(PAGES + "/trade", wait_until="domcontentloaded", timeout=60000)
        await p2.wait_for_timeout(6000)
        out["adjSettingsAfterNav"] = await p2.evaluate(
            "() => localStorage.getItem('next_settings_v2')"
        )
        await p2.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
        await p2.wait_for_selector("table tbody tr", timeout=45000)
        await p2.wait_for_timeout(3000)
        out["adjRankingsAfterReturn"] = await p2.evaluate(SCRAPE)
        await p2.close()
        await b.close()

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "browser-probe2.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    for k in ["unpriced", "priced"]:
        for n, v in out[k].items():
            print(k, n, v["rows"][:3])
    print("buttons:", out["buttons"][:40])
    print("adj first rows:", out["adjRankings"]["rows"][:3])
    print("adj after return:", out["adjRankingsAfterReturn"]["rows"][:3])


asyncio.run(main())

"""W07 browser probe: rankings surface, overrides, settings, valuation mode."""

import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

PAGES = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W07"


async def mk(pw, cookie_value):
    b = await pw.chromium.launch()
    ctx = await b.new_context(viewport={"width": 1600, "height": 1200})

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
                "value": cookie_value,
                "domain": "127.0.0.1",
                "path": "/",
            }
        ]
    )
    return b, ctx


SCRAPE = """
() => {
  const tables = Array.from(document.querySelectorAll('table'));
  let best = null, bestN = 0;
  for (const t of tables) {
    const n = t.querySelectorAll('tbody tr').length;
    if (n > bestN) { bestN = n; best = t; }
  }
  if (!best) return {headers: [], rows: [], nTables: tables.length};
  const headers = Array.from(best.querySelectorAll('thead th')).map(
      th => th.innerText.trim());
  const rows = Array.from(best.querySelectorAll('tbody tr')).map(
      tr => Array.from(tr.querySelectorAll('td,th')).map(td => td.innerText.trim()));
  return {headers, rows, nTables: tables.length};
}
"""


async def snapshot(ctx, url, settings, label):
    p = await ctx.new_page()
    errs = []
    p.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    await p.goto(PAGES + "/", wait_until="domcontentloaded")
    await p.evaluate("s => localStorage.setItem('next_settings_v2', JSON.stringify(s))", settings)
    await p.goto(PAGES + url, wait_until="domcontentloaded", timeout=60000)
    try:
        await p.wait_for_selector("table tbody tr", timeout=45000)
    except Exception as exc:
        errs.append(f"NO_TABLE: {exc}")
    await p.wait_for_timeout(4000)
    data = await p.evaluate(SCRAPE)
    data["consoleErrors"] = errs[:20]
    data["label"] = label
    data["url"] = url
    await p.close()
    return data


async def main():
    cookie = sys.argv[1]
    base_settings = json.loads(open(sys.argv[2]).read())
    async with async_playwright() as pw:
        b, ctx = await mk(pw, cookie)
        results = {}
        # 1. default board
        results["default"] = await snapshot(ctx, "/rankings", base_settings, "default")
        # 2. ktcSfTep disabled
        s2 = dict(base_settings)
        s2["siteWeights"] = {"ktcSfTep": {"include": False, "weight": 1.0}}
        results["ktcOff"] = await snapshot(ctx, "/rankings", s2, "ktcSfTep off")
        # 3. idpTradeCalc disabled
        s3 = dict(base_settings)
        s3["siteWeights"] = {"idpTradeCalc": {"include": False, "weight": 1.0}}
        results["idptcOff"] = await snapshot(ctx, "/rankings", s3, "idpTradeCalc off")
        # 4. league adjusted mode
        s4 = dict(base_settings)
        s4["valuationMode"] = "leagueAdjusted"
        results["leagueAdjusted"] = await snapshot(ctx, "/rankings", s4, "leagueAdjusted")
        await b.close()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "browser-rankings.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    for k, v in results.items():
        print(k, "headers=", v["headers"][:12], "rows=", len(v["rows"]))
        for r in v["rows"][:4]:
            print("   ", r[:10])
        print("   errs:", v["consoleErrors"][:3])


asyncio.run(main())

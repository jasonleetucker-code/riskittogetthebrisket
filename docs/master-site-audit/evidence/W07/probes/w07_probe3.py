"""W07 probe 3: in-page payload vs rendered cell, for the same page load."""

import asyncio
import json
import os

from playwright.async_api import async_playwright

PAGES = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W07"
COOKIE = "589c8aa3f7904df681c9d58413523a4e"

NAMES = [
    "Josh Allen",
    "Drake London",
    "Trey Lance",
    "Brock Bowers",
    "Bijan Robinson",
    "Austin Ekeler",
    "AJ Dillon",
    "Jahmyr Gibbs",
    "Puka Nacua",
    "T.J. Watt",
]

INPAGE = """
async (names) => {
  const res = await fetch('/api/dynasty-data', {cache:'no-store'});
  const j = await res.json();
  const c = j.data || j;
  const out = {};
  const arr = c.playersArray || [];
  const dict = c.players || {};
  for (const n of names) {
    const a = arr.find(p => p.displayName === n);
    const d = dict[n];
    out[n] = {
      fromArray: a ? {r:a.canonicalConsensusRank, v:a.rankDerivedValue, t:a.canonicalTierId} : null,
      fromDict: d ? {r:d._canonicalConsensusRank, v:d.rankDerivedValue, t:d._canonicalTierId} : null
    };
  }
  out.__meta = {hasArray: arr.length, hasDict: Object.keys(dict).length, url: res.url, status: res.status};
  return out;
}
"""

CELL = """
(name) => {
  const trs = Array.from(document.querySelectorAll('table tbody tr'));
  for (const tr of trs) {
    const tds = Array.from(tr.querySelectorAll('td,th')).map(t=>t.innerText.trim());
    if (tds.some(t => t.split('\\n')[0] === name)) return tds;
  }
  return null;
}
"""


async def main():
    async with async_playwright() as pw:
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
        p = await ctx.new_page()
        await p.goto(PAGES + "/", wait_until="domcontentloaded")
        await p.evaluate(
            "() => localStorage.setItem('next_settings_v2', "
            "JSON.stringify({valuationMode:'market', siteWeights:{}}))"
        )
        await p.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_selector("table tbody tr", timeout=45000)
        await p.wait_for_timeout(3000)
        payload = await p.evaluate(INPAGE, NAMES)
        box = p.locator("input[type=search], input[placeholder*='earch' i]").first
        rendered = {}
        for n in NAMES:
            await box.fill("")
            await box.fill(n)
            await p.wait_for_timeout(1200)
            rendered[n] = await p.evaluate(CELL, n)
        await b.close()
    res = {"payload": payload, "rendered": rendered}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "inpage-parity.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    print("meta", payload["__meta"])
    print(f"{'player':20} {'payloadRank':>11} {'domRank':>8} {'payloadVal':>10} {'domVal':>10}")
    for n in NAMES:
        pl = payload[n]["fromArray"] or payload[n]["fromDict"] or {}
        dom = rendered[n] or []
        print(
            f"{n:20} {str(pl.get('r')):>11} {(dom[0] if dom else '?'):>8} "
            f"{str(pl.get('v')):>10} {(dom[5].split(chr(10))[0] if len(dom) > 5 else '?'):>10} "
            f"tierPayload={pl.get('t')} tierDom={(dom[1] if len(dom) > 1 else '?')}"
        )


asyncio.run(main())

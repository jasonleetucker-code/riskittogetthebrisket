"""W07 probe 4: cross-page value parity for the client board vs the server board."""

import asyncio
import json
import os

from playwright.async_api import async_playwright

PAGES = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W07"
COOKIE = "589c8aa3f7904df681c9d58413523a4e"

NAMES = [
    "Brock Bowers",
    "Brevin Jordan",
    "Cade Otton",
    "Ben Sinnott",
    "AJ Barner",
    "Trey McBride",
    "Josh Allen",
    "Drake London",
    "T.J. Watt",
    "Trey Lance",
]

# Reads the row set the SHARED client hook produced, on whatever page
# we are on, by re-running the same fetch + materializer the page used.
CLIENT_BOARD = """
async (names) => {
  const res = await fetch('/api/rankings/overrides?view=delta', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tep_multiplier: 1.15}),
    cache: 'no-store'
  });
  const j = await res.json();
  const out = {};
  for (const p of (j.rankingsDelta?.players || [])) {
    if (names.includes(p.id)) out[p.id] = {v: p.rankDerivedValue, r: p.canonicalConsensusRank};
  }
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
    out = {}
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
        posts = []
        p.on(
            "request",
            lambda r: posts.append((r.url, r.post_data))
            if r.method == "POST" and "/api/" in r.url
            else None,
        )
        await p.goto(PAGES + "/", wait_until="domcontentloaded")
        await p.evaluate("() => localStorage.removeItem('next_settings_v2')")
        await p.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_selector("table tbody tr", timeout=45000)
        await p.wait_for_timeout(4000)
        out["postsOnDefaultLoad"] = [{"url": u, "body": (d or "")[:400]} for u, d in posts]
        out["storedSettingsAfterLoad"] = await p.evaluate(
            "() => localStorage.getItem('next_settings_v2')"
        )
        box = p.locator("input[type=search], input[placeholder*='earch' i]").first
        rankings = {}
        for n in NAMES:
            await box.fill("")
            await box.fill(n)
            await p.wait_for_timeout(1100)
            rankings[n] = await p.evaluate(CELL, n)
        out["rankingsCells"] = rankings
        out["clientBoard"] = await p.evaluate(CLIENT_BOARD, NAMES)
        await b.close()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "cross-page-parity.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("POSTs fired on a DEFAULT (never-touched-settings) load:")
    for x in out["postsOnDefaultLoad"]:
        print("  ", x["url"], "->", x["body"][:200])
    print("stored settings after load:", (out["storedSettingsAfterLoad"] or "")[:300])
    for n in NAMES:
        c = rankings[n]
        print(
            f"{n:16} #{(c[0] if c else '?'):>5}  value={(c[5].split(chr(10))[0] if c and len(c) > 5 else '?'):>8}"
        )


asyncio.run(main())

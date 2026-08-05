"""W07 probe 6: real /settings UI interaction -> /rankings, plus CSV export parity."""

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
  let best=null,n=0;
  for (const t of tables){const k=t.querySelectorAll('tbody tr').length; if(k>n){n=k;best=t;}}
  if(!best) return {headers:[],rows:[]};
  return {
    headers: Array.from(best.querySelectorAll('thead th')).map(x=>x.innerText.trim()),
    rows: Array.from(best.querySelectorAll('tbody tr')).map(
      tr=>Array.from(tr.querySelectorAll('td,th')).map(td=>td.innerText.trim()))
  };
}
"""


async def main():
    out = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1600, "height": 1400}, accept_downloads=True)

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
        reqs = []
        p.on(
            "request",
            lambda r: reqs.append((r.method, r.url, (r.post_data or "")[:300]))
            if "/api/rankings/overrides" in r.url
            else None,
        )
        await p.goto(PAGES + "/", wait_until="domcontentloaded")
        await p.evaluate("() => localStorage.removeItem('next_settings_v2')")

        # --- Real UI interaction on /settings: uncheck a source ---
        await p.goto(PAGES + "/settings", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_timeout(6000)
        n0 = len(reqs)
        # find the checkbox row for KeepTradeCut SF-TE++
        boxes = p.locator("input[type=checkbox]")
        cnt = await boxes.count()
        out["checkboxCount"] = cnt
        labels = await p.evaluate("""
          () => Array.from(document.querySelectorAll('input[type=checkbox]')).map(
            (b,i) => ({i, aria: b.getAttribute('aria-label'),
                       ctx: (b.closest('tr,li,div')||{}).innerText?.slice(0,60)}))
        """)
        out["checkboxLabels"] = labels[:40]
        target = next(
            (x for x in labels if x["aria"] and "KeepTradeCut SF-TE++" in x["aria"]),
            None,
        )
        out["target"] = target
        if target is not None:
            await boxes.nth(target["i"]).uncheck()
            await p.wait_for_timeout(3000)
        out["settingsAfterUncheck"] = await p.evaluate(
            "() => localStorage.getItem('next_settings_v2')"
        )
        out["overridePostsFromSettings"] = [{"m": m, "u": u, "b": bd} for m, u, bd in reqs[n0:]]

        # --- Now load /rankings and read the board ---
        await p.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_selector("table tbody tr", timeout=45000)
        await p.wait_for_timeout(5000)
        out["boardAfterUncheck"] = (await p.evaluate(SCRAPE))["rows"][:12]
        out["overridePostsAll"] = [{"m": m, "u": u, "b": bd} for m, u, bd in reqs]

        # --- CSV export vs screen ---
        screen = await p.evaluate(SCRAPE)
        async with p.expect_download(timeout=30000) as dl:
            await p.locator("text=Export CSV").first.click()
        d = await dl.value
        path = os.path.join(OUT, "export.csv")
        await d.save_as(path)
        with open(path) as fh:
            csv = fh.read()
        out["csvHead"] = csv.split("\n")[:8]
        out["csvLineCount"] = len(csv.strip().split("\n"))
        out["screenRowCount"] = len(screen["rows"])
        out["screenHeaders"] = screen["headers"]
        out["screenFirst6"] = screen["rows"][:6]
        await b.close()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "settings-and-export.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("target checkbox:", out["target"])
    print("settings after uncheck:", (out["settingsAfterUncheck"] or "")[:300])
    print("override POSTs:")
    for r in out["overridePostsAll"]:
        print("  ", r["b"][:200])
    print("board after uncheck:", [r[:6] for r in out["boardAfterUncheck"][:5]])
    print("csv lines", out["csvLineCount"], "screen rows", out["screenRowCount"])
    print("csv head:", out["csvHead"][:4])
    print("screen headers:", out["screenHeaders"])


asyncio.run(main())

"""W07 probe 5: valuation-mode toggle wiring, persistence and engine reach."""

import asyncio
import json
import os

from playwright.async_api import async_playwright

PAGES = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W07"
COOKIE = "589c8aa3f7904df681c9d58413523a4e"

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
        reqs = []
        p.on(
            "request",
            lambda r: reqs.append((r.method, r.url, (r.post_data or "")[:200]))
            if "/api/" in r.url
            else None,
        )
        await p.goto(PAGES + "/", wait_until="domcontentloaded")
        await p.evaluate("() => localStorage.removeItem('next_settings_v2')")
        await p.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_selector("table tbody tr", timeout=45000)
        await p.wait_for_timeout(4000)
        n0 = len(reqs)
        # Click the "My league" lens toggle
        btn = p.locator("text=My league").first
        await btn.click()
        await p.wait_for_timeout(6000)
        out["requestsAfterToggle"] = [{"m": m, "u": u, "b": bd} for m, u, bd in reqs[n0:]]
        out["settingsAfterToggle"] = await p.evaluate(
            "() => localStorage.getItem('next_settings_v2')"
        )
        out["cellAfterToggle"] = {}
        box = p.locator("input[type=search], input[placeholder*='earch' i]").first
        for name in ["Josh Allen", "Brevin Jordan", "T.J. Watt"]:
            await box.fill("")
            await box.fill(name)
            await p.wait_for_timeout(1100)
            out["cellAfterToggle"][name] = await p.evaluate(CELL, name)
        # Reload -> does the lens survive?
        await p.goto(PAGES + "/rankings", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_selector("table tbody tr", timeout=45000)
        await p.wait_for_timeout(4000)
        out["cellAfterReload"] = {}
        box = p.locator("input[type=search], input[placeholder*='earch' i]").first
        for name in ["Josh Allen", "Brevin Jordan", "T.J. Watt"]:
            await box.fill("")
            await box.fill(name)
            await p.wait_for_timeout(1100)
            out["cellAfterReload"][name] = await p.evaluate(CELL, name)
        out["settingsAfterReload"] = await p.evaluate(
            "() => localStorage.getItem('next_settings_v2')"
        )
        n1 = len(reqs)
        # Navigate to /trade -> does the engine request carry the mode?
        await p.goto(PAGES + "/trade", wait_until="domcontentloaded", timeout=60000)
        await p.wait_for_timeout(9000)
        out["tradeRequests"] = [{"m": m, "u": u, "b": bd} for m, u, bd in reqs[n1:]]
        await b.close()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "valuation-mode.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("settings after toggle:", (out["settingsAfterToggle"] or "")[:400])
    print("requests after toggle:")
    for r in out["requestsAfterToggle"]:
        print("  ", r["m"], r["u"], r["b"][:120])
    for k in ("cellAfterToggle", "cellAfterReload"):
        print(k, {n: (v[0], v[5]) if v else None for n, v in out[k].items()})
    print("trade requests:")
    for r in out["tradeRequests"]:
        print("  ", r["m"], r["u"], r["b"][:160])


asyncio.run(main())

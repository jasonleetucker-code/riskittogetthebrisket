import asyncio
import json
import os
import re
from playwright.async_api import async_playwright

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
URLS = [
    "/league/activity",
    "/league/franchise/468418790212759552",
    "/league/franchise/714976074907336704",
    "/league/franchise/jason",
    "/league/player/6794",
    "/league/player/99999999",
    "/league/rivalry/468418790212759552-vs-711452264774041600",
    "/league/week/2025/17",
    "/league/week/2026/1",
    "/league/weekly/2025/17/1",
    "/league/articles/2025/17",
    "/league/articles/2026/1",
    "/league/articles/2025/17/1/recap",
]


async def main():
    out = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1440, "height": 1200})

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        for path in URLS:
            p = await ctx.new_page()
            errs = []
            p.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            st = None
            try:
                r = await p.goto(
                    "http://127.0.0.1:3000" + path, wait_until="domcontentloaded", timeout=40000
                )
                st = r.status if r else None
            except Exception as e:
                errs.append(f"NAV:{e}")
            await p.wait_for_timeout(3500)
            t = re.sub(r"\s+", " ", await p.inner_text("body")).strip()
            out.append(
                {"path": path, "status": st, "chars": len(t), "text": t[:700], "errs": errs[:3]}
            )
            await p.close()
        await b.close()
    json.dump(
        out,
        open(
            "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/deeplink-probe.json",
            "w",
        ),
        indent=1,
    )
    for o in out:
        print(f"### {o['path']}  st={o['status']} chars={o['chars']}")
        print("   ", o["text"][:420])
        print()


asyncio.run(main())

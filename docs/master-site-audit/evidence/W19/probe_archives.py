"""Deep probe of the /league?tab=archives lazy fetch."""

import asyncio
import json
import os
import re

from playwright.async_api import async_playwright

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1200})
        reqs = []

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                reqs.append(("REWRITTEN", u))
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                if "/api/" in u:
                    reqs.append(("DIRECT", u))
                await r.continue_()

        await ctx.route("**/*", route)
        page = await ctx.new_page()
        resps = []
        page.on(
            "response",
            lambda r: resps.append((r.status, r.url)) if "/api/" in r.url else None,
        )
        errs = []
        page.on("console", lambda m: errs.append(f"{m.type}:{m.text}"))
        page.on("pageerror", lambda e: errs.append(f"PAGEERROR:{e}"))
        await page.goto("http://127.0.0.1:3000/league?tab=archives", wait_until="networkidle")
        await page.wait_for_timeout(15000)
        body = re.sub(r"\s+", " ", await page.inner_text("body")).strip()
        out = {
            "requests": reqs,
            "apiResponses": resps,
            "console": errs[:40],
            "text": body[:2500],
            "stillLoading": "Loading section" in body,
        }
        print(json.dumps(out, indent=1)[:6000])
        await page.screenshot(
            path="/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/archives-15s.png"
        )
        await browser.close()


asyncio.run(main())

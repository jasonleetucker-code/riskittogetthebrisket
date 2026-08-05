import asyncio
import json
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context()

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        errs = []
        pg = await ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        resp = await pg.goto(
            "http://127.0.0.1:3000/league?tab=teamAssignment",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await pg.wait_for_timeout(9000)
        html = await pg.content()
        txt = await pg.inner_text("body")
        out = {
            "status": resp.status,
            "url": pg.url,
            "bytes": len(html),
            "consoleErrors": errs[:10],
            "hasFavoriteChip": "FAVORITE" in txt.upper(),
            "hasRosterBased": "ROSTER-BASED" in txt.upper(),
            "mentionsRookieDraftCapital": "draft capital" in txt.lower(),
            "nflNamesFound": [
                n
                for n in [
                    "Minnesota Vikings",
                    "Green Bay Packers",
                    "Houston Texans",
                    "Miami Dolphins",
                    "Kansas City Chiefs",
                ]
                if n in txt
            ],
            "showBreakdownButtons": await pg.locator("button:has-text('Show breakdown')").count(),
            "textSample": txt[:1600],
        }
        print(json.dumps(out, indent=1))
        # click a breakdown
        if out["showBreakdownButtons"]:
            await pg.locator("button:has-text('Show breakdown')").first.click()
            await pg.wait_for_timeout(800)
            t2 = await pg.inner_text("body")
            print(
                "BREAKDOWN_SAMPLE:", [ln for ln in t2.split("\n") if "pts" in ln or "+" in ln][:20]
            )
        await b.close()


asyncio.run(main())

"""Build a real trade in the browser and record the rendered verdict."""

import asyncio
import json

from playwright.async_api import async_playwright

SECRET_PATH = (
    "/tmp/claude-0/-home-user-riskittogetthebrisket/"
    "0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"
)


async def add(page, side_idx, name):
    boxes = await page.query_selector_all("input.trade-side-search-input")
    box = boxes[side_idx]
    await box.click()
    await box.fill("")
    await box.type(name, delay=15)
    await page.wait_for_timeout(600)
    res = await page.query_selector_all(
        ".trade-side-search-results button, .trade-side-search-results [role=option]"
    )
    if not res:
        res = await page.query_selector_all(".trade-side-search-results *")
    for r in res:
        txt = (await r.inner_text()) or ""
        if name.lower() in txt.lower():
            await r.click()
            await page.wait_for_timeout(400)
            return True
    return False


async def main() -> None:
    secret = open(SECRET_PATH).read().strip()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        page = await ctx.new_page()
        await page.request.post(
            "http://127.0.0.1:8000/api/test/create-session",
            headers={"Authorization": f"Bearer {secret}"},
        )
        await ctx.add_cookies(
            [
                {**c, "domain": "127.0.0.1"}
                for c in await ctx.cookies()
                if "127.0.0.1" in c["domain"]
            ]
        )
        await page.goto("http://127.0.0.1:3000/trade", wait_until="networkidle")
        await page.wait_for_timeout(4000)

        out = {}
        out["addedA"] = await add(page, 0, "Sam LaPorta")
        out["addedB"] = await add(page, 1, "Sonny Styles")
        await page.wait_for_timeout(800)

        async def snap(tag):
            meter = await page.query_selector(".trade-meter")
            rec = {
                "meter": (await meter.inner_text()) if meter else None,
                "sideTotals": await page.eval_on_selector_all(
                    "[class*=sideTotals]", "els=>els.map(e=>e.innerText)"
                ),
            }
            out[tag] = rec
            return rec

        print("OUR VALUE:", json.dumps(await snap("ourValue"), indent=1))
        # flip to Raw
        for b in await page.query_selector_all("button"):
            if ((await b.inner_text()) or "").strip() == "Raw":
                await b.click()
                break
        await page.wait_for_timeout(800)
        print("RAW:", json.dumps(await snap("raw"), indent=1))

        body = await page.inner_text("body")
        out["bodyText"] = body
        json.dump(out, open("page_probe3.json", "w"), indent=1)
        await browser.close()


asyncio.run(main())

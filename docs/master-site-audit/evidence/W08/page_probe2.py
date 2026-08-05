"""Interact with the /trade side search box and record what it offers."""

import asyncio
import json

from playwright.async_api import async_playwright

SECRET_PATH = (
    "/tmp/claude-0/-home-user-riskittogetthebrisket/"
    "0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"
)
OUT = "page_probe2.json"


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

        inputs = await page.query_selector_all("input")
        meta = []
        for i, el in enumerate(inputs):
            meta.append(
                {
                    "i": i,
                    "type": await el.get_attribute("type"),
                    "placeholder": await el.get_attribute("placeholder"),
                    "aria": await el.get_attribute("aria-label"),
                    "visible": await el.is_visible(),
                }
            )
        out = {"inputs": meta, "queries": {}}

        target = None
        for el, m in zip(inputs, meta):
            ph = (m["placeholder"] or "") + (m["aria"] or "")
            if m["visible"] and (
                "add" in ph.lower() or "player" in ph.lower() or "pick" in ph.lower()
            ):
                target = el
                break
        if target is not None:
            for q in [
                "2026 Pick 1.0",
                "2026",
                "2027 Mid 1st",
                "2029 Early 1st",
                "Josh Allen",
                "Micah Parsons",
                "AJ Dillon",
            ]:
                await target.click()
                await target.fill("")
                await target.type(q, delay=15)
                await page.wait_for_timeout(700)
                opts = await page.eval_on_selector_all(
                    "[role=option], li, button",
                    "els=>els.map(e=>e.innerText).filter(t=>t&&t.length<120)",
                )
                out["queries"][q] = opts[:40]
                await target.fill("")
                await page.wait_for_timeout(200)
        json.dump(out, open(OUT, "w"), indent=1)
        print(json.dumps(out, indent=1)[:6000])
        await browser.close()


asyncio.run(main())

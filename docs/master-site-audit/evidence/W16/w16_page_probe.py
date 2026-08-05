import asyncio
import re
from playwright.async_api import async_playwright

SECRET = (
    open(
        "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"
    )
    .read()
    .strip()
)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context()
        api = await ctx.request.post(
            "http://127.0.0.1:8000/api/test/create-session",
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        print("session", api.status)
        # copy backend cookies onto :3000 origin
        st = await ctx.storage_state()
        newc = []
        for c in st["cookies"]:
            d = dict(c)
            d["domain"] = "127.0.0.1"
            d.pop("sameSite", None)
            newc.append(d)
        await ctx.add_cookies(newc)

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        pg = await ctx.new_page()
        resp = await pg.goto(
            "http://127.0.0.1:3000/league/insider-trading", wait_until="networkidle"
        )
        print("status", resp.status, "url", pg.url)
        txt = await pg.inner_text("body")
        print("----TEXT----")
        print(re.sub(r"\n{2,}", "\n", txt)[:2500])
        await b.close()


asyncio.run(main())

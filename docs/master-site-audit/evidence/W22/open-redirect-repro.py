import asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context()
        offsite = []

        async def route(r):
            u = r.request.url
            host = urlparse(u).hostname or ""
            if host.endswith("evil.com"):
                offsite.append(u)
                await r.abort()
            elif "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8001"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        pg = await ctx.new_page()
        trail = []
        pg.on("framenavigated", lambda f: trail.append(f.url))
        await pg.goto(
            "http://127.0.0.1:3000/login?next=/%5Cevil.com", wait_until="domcontentloaded"
        )
        print(
            "resolves ->",
            await pg.evaluate("() => new URL(String.raw`/\\evil.com`, location.href).href"),
        )
        await pg.fill("input[type=text], input[name=username]", "jasonleetucker")
        await pg.fill("input[type=password]", "changeme")
        await pg.click("button[type=submit]")
        await pg.wait_for_timeout(4000)
        print("final url:", pg.url)
        print("offsite requests:", offsite)
        print("frame trail:", trail[-4:])
        await b.close()


asyncio.run(main())

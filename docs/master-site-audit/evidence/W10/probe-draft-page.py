import asyncio
import os

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
from playwright.async_api import async_playwright

SECRET_PATH = "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"


async def main():
    import urllib.request

    secret = open(SECRET_PATH).read().strip()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/test/create-session",
        method="POST",
        headers={"Authorization": f"Bearer {secret}"},
    )
    resp = urllib.request.urlopen(req)
    cookie = resp.headers.get("set-cookie")
    name, value = cookie.split(";")[0].split("=", 1)

    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context()
        await ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        pg = await ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        await pg.goto("http://127.0.0.1:3000/draft", wait_until="networkidle", timeout=90000)
        await pg.wait_for_timeout(6000)
        html = await pg.content()
        open("/tmp/w10_draft.html", "w").write(html)
        print("bytes", len(html))
        h1 = await pg.locator("h1").first.text_content()
        print("h1", h1)
        # dump team panel text
        txt = await pg.locator("body").inner_text()
        open("/tmp/w10_draft.txt", "w").write(txt)
        for line in txt.splitlines():
            if "Russini" in line or "slot" in line.lower() or "Slots" in line:
                print("TXT:", line[:160])
        print("console errors:", errs[:5])
        await b.close()


asyncio.run(main())

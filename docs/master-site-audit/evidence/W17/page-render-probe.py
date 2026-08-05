import asyncio
import json
from playwright.async_api import async_playwright

PAGES = [
    ("/league?tab=rosTradeDeadline", "rosTradeDeadline"),
    ("/league?tab=rosChampionship", "rosChampionship"),
    ("/league?tab=rosTeamStrength", "rosTeamStrength"),
    ("/tools/ros-data-health", "rosDataHealth"),
]


async def main():
    secret = (
        open(
            "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"
        )
        .read()
        .strip()
    )
    out = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context()

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        p = await ctx.new_page()
        await p.request.post(
            "http://127.0.0.1:8000/api/test/create-session",
            headers={"Authorization": f"Bearer {secret}"},
        )
        cookies = await p.request.storage_state()
        await ctx.add_cookies(
            [{**c, "domain": "127.0.0.1", "path": "/"} for c in cookies.get("cookies", [])]
        )
        for path, key in PAGES:
            errs = []
            p.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            await p.goto("http://127.0.0.1:3000" + path, wait_until="networkidle", timeout=60000)
            await p.wait_for_timeout(3500)
            txt = await p.inner_text("body")
            out[key] = {
                "url": path,
                "chars": len(txt),
                "text": txt[:6000],
                "consoleErrors": errs[:8],
            }
            print("=" * 20, key, len(txt))
            print(txt[:3000])
        await b.close()
    json.dump(out, open("docs/master-site-audit/evidence/W17/page-render.json", "w"), indent=1)


asyncio.run(main())

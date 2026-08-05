"""Which requests are still outstanding when networkidle never fires."""

import asyncio
import json
import sys
import urllib.request

from playwright.async_api import async_playwright

BACKEND = "http://127.0.0.1:8000"
FRONT = "http://127.0.0.1:3000"
TARGETS = ["/rankings", "/rosters", "/finder", "/league", "/draft", "/trade"]


async def main():
    secret = (
        open(
            "/tmp/claude-0/-home-user-riskittogetthebrisket/"
            "0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"
        )
        .read()
        .strip()
    )
    req = urllib.request.Request(
        BACKEND + "/api/test/create-session",
        method="POST",
        headers={"Authorization": "Bearer " + secret},
    )
    with urllib.request.urlopen(req) as r:
        hdrs = r.headers.get_all("Set-Cookie") or []
        r.read()
    cookies = []
    for h in hdrs:
        n, _, v = h.split(";")[0].partition("=")
        cookies.append({"name": n.strip(), "value": v.strip(), "domain": "127.0.0.1", "path": "/"})

    out = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1366, "height": 900})
        await ctx.add_cookies(cookies)

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith(FRONT):
                await r.continue_(url=u.replace(FRONT, BACKEND))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        for t in TARGETS:
            page = await ctx.new_page()
            inflight = {}
            timeline = []
            loop = asyncio.get_event_loop()
            t0 = loop.time()

            def on_req(r):
                inflight[r] = (r.url, int((loop.time() - t0) * 1000))

            def on_done(r):
                s = inflight.pop(r, None)
                if s:
                    timeline.append(
                        {
                            "url": s[0][:150],
                            "startMs": s[1],
                            "endMs": int((loop.time() - t0) * 1000),
                            "durMs": int((loop.time() - t0) * 1000) - s[1],
                        }
                    )

            def on_fail(r):
                s = inflight.pop(r, None)
                if s:
                    timeline.append(
                        {
                            "url": s[0][:150],
                            "startMs": s[1],
                            "endMs": int((loop.time() - t0) * 1000),
                            "failed": r.failure,
                        }
                    )

            page.on("request", on_req)
            page.on("requestfinished", on_done)
            page.on("requestfailed", on_fail)
            await page.goto(FRONT + t, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(26)
            still = [{"url": u[:150], "startMs": s} for (u, s) in inflight.values()]
            timeline.sort(key=lambda x: -(x.get("durMs") or 0))
            out.append(
                {
                    "route": t,
                    "stillPending": still,
                    "slowest": timeline[:10],
                    "totalRequests": len(timeline) + len(still),
                }
            )
            print(t, "pending:", len(still), [p["url"][-70:] for p in still][:5], flush=True)
            print(
                "  slowest:", [(x["url"][-55:], x.get("durMs")) for x in timeline[:4]], flush=True
            )
            await page.close()
        await ctx.close()
        await b.close()
    json.dump(out, open(sys.argv[1], "w"), indent=1)


asyncio.run(main())

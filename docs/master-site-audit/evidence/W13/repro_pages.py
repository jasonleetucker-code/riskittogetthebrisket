"""W13: prove BDVM surfaces self-suppress / disclose at runtime."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(sys.argv[1])
COOKIES = Path("/tmp/w13-cookies.txt")


def load_cookies():
    out = []
    for line in COOKIES.read_text().splitlines():
        line = line.replace("#HttpOnly_", "")
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            out.append(
                {
                    "name": parts[5],
                    "value": parts[6],
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            )
    return out


async def main():
    result = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        await ctx.add_cookies(load_cookies())

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)

        api_calls = []

        for name, url, wait in (
            ("bdvm", "http://127.0.0.1:3000/bdvm", 8000),
            ("rankings", "http://127.0.0.1:3000/rankings", 15000),
            ("draft", "http://127.0.0.1:3000/draft", 15000),
        ):
            page = await ctx.new_page()
            page.on(
                "response",
                lambda r: api_calls.append((r.url, r.status)) if "/api/bdvm/" in r.url else None,
            )
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(wait)
            body = await page.inner_text("body")
            headers = [
                (await th.inner_text()).strip()
                for th in await page.query_selector_all("table thead th")
            ]
            result[name] = {
                "status": resp.status if resp else None,
                "hasFundGapHeader": any("Fund gap" in h for h in headers),
                "headerSample": headers[:40],
                "bodyMentionsProjectionSnapshot": "projection snapshot" in body.lower(),
                "bodyMentionsFundamentals": "fundamental" in body.lower(),
                "bodyLen": len(body),
                "bodyExcerpt": body[:1200],
            }
            await page.close()
        result["bdvmApiCalls"] = api_calls
        await browser.close()
    OUT.write_text(json.dumps(result, indent=1))
    for k, v in result.items():
        if k == "bdvmApiCalls":
            print("api calls:", v)
        else:
            print(
                k,
                "status",
                v["status"],
                "| FundGap col:",
                v["hasFundGapHeader"],
                "| snapshot msg:",
                v["bodyMentionsProjectionSnapshot"],
            )


asyncio.run(main())

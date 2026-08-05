"""Screenshots + keyboard/focus + hover-only affordance checks."""

import asyncio
import json
import sys
import urllib.request

from playwright.async_api import async_playwright

BACKEND = "http://127.0.0.1:8000"
FRONT = "http://127.0.0.1:3000"
OUT = sys.argv[1]

SHOTS = [
    ("/rankings", "desktop"),
    ("/rankings", "mobile"),
    ("/draft", "mobile"),
    ("/draft", "desktop"),
    ("/rosters", "desktop"),
    ("/league-comparison", "desktop"),
    ("/", "mobile"),
    ("/trade", "mobile"),
]

FOCUS_JS = r"""
() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const r = el.getBoundingClientRect();
  const st = getComputedStyle(el);
  return {
    tag: el.tagName.toLowerCase(),
    text: (el.innerText || el.getAttribute('aria-label') || el.value || '').trim().slice(0, 40),
    cls: String(el.className || '').slice(0, 50),
    x: Math.round(r.x), y: Math.round(r.y),
    w: Math.round(r.width), h: Math.round(r.height),
    outline: st.outlineStyle + ' ' + st.outlineWidth + ' ' + st.outlineColor,
    boxShadow: st.boxShadow.slice(0, 60),
    offscreen: r.width === 0 && r.height === 0,
  };
}
"""

HOVER_ONLY_JS = r"""
() => {
  // Elements whose ONLY explanation of themselves is a title= tooltip.
  const withTitle = Array.from(document.querySelectorAll('[title]'));
  const out = { titleCount: withTitle.length, samples: [] };
  for (const el of withTitle.slice(0, 400)) {
    const t = el.getAttribute('title') || '';
    if (!/scale|value|rank|means|per-source|breakdown|confidence|spread/i.test(t)) continue;
    out.samples.push({
      tag: el.tagName.toLowerCase(),
      title: t.slice(0, 90),
      hasAriaLabel: !!el.getAttribute('aria-label'),
      focusable: el.tabIndex >= 0 || ['a', 'button', 'input', 'select'].includes(el.tagName.toLowerCase()),
      text: (el.innerText || '').trim().slice(0, 24),
    });
    if (out.samples.length >= 10) break;
  }
  // Visible text anywhere on the page that states the scale
  const body = document.body.innerText || '';
  out.scaleStatedInVisibleText = /9,?999|0\s*[-–]\s*9,?999|1\s*[-–]\s*9,?999/.test(body);
  return out;
}
"""


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

    report = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for path, vp in SHOTS:
            w, h = (1366, 900) if vp == "desktop" else (390, 844)
            ctx = await b.new_context(
                viewport={"width": w, "height": h},
                is_mobile=(vp == "mobile"),
                has_touch=(vp == "mobile"),
            )
            await ctx.add_cookies(cookies)

            async def route(r):
                u = r.request.url
                if "/api/" in u and u.startswith(FRONT):
                    await r.continue_(url=u.replace(FRONT, BACKEND))
                else:
                    await r.continue_()

            await ctx.route("**/*", route)
            page = await ctx.new_page()
            await page.goto(FRONT + path, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
            name = (path.strip("/") or "home").replace("/", "-") + "-" + vp
            await page.screenshot(path=f"{OUT}/{name}.png", full_page=False)
            entry = {"route": path, "viewport": vp, "shot": f"{name}.png"}
            entry["hoverOnly"] = await page.evaluate(HOVER_ONLY_JS)
            # keyboard tab order, first 22 stops
            stops = []
            for _ in range(22):
                await page.keyboard.press("Tab")
                s = await page.evaluate(FOCUS_JS)
                stops.append(s)
            entry["tabStops"] = stops
            entry["noFocusRing"] = sum(
                1
                for s in stops
                if s
                and s["outline"].startswith("none")
                and (not s["boxShadow"] or s["boxShadow"] == "none")
            )
            report.append(entry)
            print(
                path,
                vp,
                "titleTooltips=",
                entry["hoverOnly"]["titleCount"],
                "scaleVisible=",
                entry["hoverOnly"]["scaleStatedInVisibleText"],
                "noFocusRing=",
                entry["noFocusRing"],
                "/22",
                flush=True,
            )
            await ctx.close()
        await b.close()
    json.dump(report, open(f"{OUT}/focus-hover-report.json", "w"), indent=1)


asyncio.run(main())

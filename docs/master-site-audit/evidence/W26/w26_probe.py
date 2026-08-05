"""W26 browser probe: perf timings + duplicate requests + a11y/mobile DOM checks."""

import asyncio
import json
import re
import sys

from playwright.async_api import async_playwright

BACKEND = "http://127.0.0.1:8000"
FRONT = "http://127.0.0.1:3000"

PAGES = [
    "/",
    "/rankings",
    "/trade",
    "/draft",
    "/terminal",
    "/waivers",
    "/news",
    "/settings",
    "/bdvm",
    "/league",
    "/rosters",
    "/finder",
    "/market/sharp-roster-percentage",
    "/league-comparison",
]

VIEWPORTS = {"desktop": (1366, 900), "mobile": (390, 844)}

DOM_JS = r"""
() => {
  const out = {};
  const de = document.documentElement;
  out.scrollWidth = de.scrollWidth;
  out.clientWidth = de.clientWidth;
  out.horizontalOverflow = de.scrollWidth > de.clientWidth + 1;

  // widest offending elements
  const over = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > de.clientWidth + 2) {
      over.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && String(el.className).slice(0, 60)) || '',
        right: Math.round(r.right),
        w: Math.round(r.width),
      });
    }
  }
  over.sort((a, b) => b.right - a.right);
  out.overflowing = over.slice(0, 6);

  // touch targets
  const small = [];
  const interactive = document.querySelectorAll(
    'a[href],button,input,select,textarea,[role="button"],[role="tab"],[role="link"],[onclick],[tabindex]:not([tabindex="-1"])'
  );
  out.interactiveCount = interactive.length;
  for (const el of interactive) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    if (r.height < 44 || r.width < 44) {
      small.push({
        tag: el.tagName.toLowerCase(),
        text: (el.innerText || el.getAttribute('aria-label') || el.value || '').trim().slice(0, 34),
        w: Math.round(r.width),
        h: Math.round(r.height),
      });
    }
  }
  out.smallTargetCount = small.length;
  out.smallTargets = small.slice(0, 12);

  // unlabelled interactive controls
  const unlabelled = [];
  for (const el of interactive) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const txt = (el.innerText || '').trim();
    const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title');
    let lab = null;
    if (el.id) lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    if (!txt && !aria && !lab && !el.closest('label')) {
      unlabelled.push({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        cls: (el.className && String(el.className).slice(0, 50)) || '',
      });
    }
  }
  out.unlabelledCount = unlabelled.length;
  out.unlabelled = unlabelled.slice(0, 10);

  // images without alt
  out.imgNoAlt = Array.from(document.images).filter((i) => !i.hasAttribute('alt')).length;
  out.imgCount = document.images.length;

  // table semantics
  const tables = Array.from(document.querySelectorAll('table'));
  out.tables = tables.map((t) => ({
    rows: t.rows.length,
    th: t.querySelectorAll('th').length,
    thScope: t.querySelectorAll('th[scope]').length,
    caption: !!t.querySelector('caption'),
    ariaLabel: !!(t.getAttribute('aria-label') || t.getAttribute('aria-labelledby')),
    scrollW: t.scrollWidth,
    clientW: t.clientWidth,
    parentScrolls: (() => {
      const p = t.parentElement;
      if (!p) return false;
      const st = getComputedStyle(p);
      return st.overflowX === 'auto' || st.overflowX === 'scroll';
    })(),
  }));
  out.gridRoleCount = document.querySelectorAll('[role="table"],[role="grid"],[role="rowgroup"]').length;

  // headings / landmarks
  out.h1Count = document.querySelectorAll('h1').length;
  out.headingOrder = Array.from(document.querySelectorAll('h1,h2,h3,h4')).map((h) => h.tagName).slice(0, 24);
  out.landmarks = {
    main: document.querySelectorAll('main,[role="main"]').length,
    nav: document.querySelectorAll('nav,[role="navigation"]').length,
    skipLink: !!document.querySelector('a[href^="#"][class*="skip" i], a[class*="skip" i]'),
  };
  out.lang = document.documentElement.getAttribute('lang') || null;

  // contrast: sample visible text nodes, compute fg/bg ratio
  function parseRGB(s) {
    const m = String(s).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }
  function lum(c) {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function effBg(el) {
    let n = el;
    while (n && n !== document.documentElement) {
      const c = parseRGB(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0.5) return c;
      n = n.parentElement;
    }
    const c = parseRGB(getComputedStyle(document.body).backgroundColor);
    return c && c.a > 0.5 ? c : { r: 255, g: 255, b: 255, a: 1 };
  }
  const low = [];
  let checked = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  let node;
  while ((node = walker.nextNode())) {
    const t = (node.textContent || '').trim();
    if (t.length < 2) continue;
    const el = node.parentElement;
    if (!el || seen.has(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) < 0.2) continue;
    const fg = parseRGB(st.color);
    if (!fg) continue;
    const bg = effBg(el);
    const L1 = lum(fg), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    checked++;
    const fs = parseFloat(st.fontSize);
    const bold = parseInt(st.fontWeight, 10) >= 700;
    const large = fs >= 24 || (fs >= 18.66 && bold);
    const need = large ? 3.0 : 4.5;
    if (ratio < need) {
      low.push({
        text: t.slice(0, 34),
        ratio: Math.round(ratio * 100) / 100,
        need,
        fg: st.color,
        bg: 'rgb(' + Math.round(bg.r) + ',' + Math.round(bg.g) + ',' + Math.round(bg.b) + ')',
        fontSize: fs,
        cls: (el.className && String(el.className).slice(0, 46)) || '',
      });
    }
  }
  out.contrastChecked = checked;
  out.contrastFailCount = low.length;
  low.sort((a, b) => a.ratio - b.ratio);
  out.contrastWorst = low.slice(0, 10);

  // tiny fonts
  const tiny = new Set();
  for (const el of document.querySelectorAll('body *')) {
    const st = getComputedStyle(el);
    const fs = parseFloat(st.fontSize);
    if (fs && fs < 11 && (el.innerText || '').trim().length > 1) tiny.add(Math.round(fs * 10) / 10);
  }
  out.tinyFontSizes = Array.from(tiny).sort();

  out.bodyText = (document.body.innerText || '').slice(0, 6000);
  return out;
}
"""


async def probe(page_path, vp_name, ctx, results):
    page = await ctx.new_page()
    reqs = []
    page.on("request", lambda r: reqs.append(r.url))
    console = []
    page.on(
        "console",
        lambda m: console.append(f"{m.type}: {m.text}"[:220])
        if m.type in ("error", "warning")
        else None,
    )
    entry = {"route": page_path, "viewport": vp_name}
    try:
        t0 = asyncio.get_event_loop().time()
        resp = await page.goto(FRONT + page_path, wait_until="domcontentloaded", timeout=60000)
        entry["status"] = resp.status if resp else None
        entry["navMs"] = int((asyncio.get_event_loop().time() - t0) * 1000)
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            entry["networkIdleTimeout"] = True
        entry["settleMs"] = int((asyncio.get_event_loop().time() - t0) * 1000)
        entry["finalUrl"] = page.url.replace(FRONT, "")
        nav = await page.evaluate(
            "() => { const n = performance.getEntriesByType('navigation')[0] || {};"
            " const p = performance.getEntriesByType('paint');"
            " const rs = performance.getEntriesByType('resource');"
            " return {domContentLoaded: Math.round(n.domContentLoadedEventEnd||0),"
            " load: Math.round(n.loadEventEnd||0),"
            " fcp: Math.round((p.find(x=>x.name==='first-contentful-paint')||{}).startTime||0),"
            " resourceCount: rs.length,"
            " transferBytes: rs.reduce((a,r)=>a+(r.transferSize||0),0),"
            " decodedBytes: rs.reduce((a,r)=>a+(r.decodedBodySize||0),0)}; }"
        )
        entry["timing"] = nav
        api = [u for u in reqs if "/api/" in u]
        counts = {}
        for u in api:
            k = re.sub(r"[?&]_rsc=[^&]*", "", u).replace(FRONT, "").replace(BACKEND, "")
            counts[k] = counts.get(k, 0) + 1
        entry["apiCallCount"] = len(api)
        entry["apiDuplicates"] = {k: v for k, v in counts.items() if v > 1}
        entry["apiUnique"] = sorted(counts)
        entry["dom"] = await page.evaluate(DOM_JS)
        entry["consoleErrors"] = [c for c in console if c.startswith("error")][:8]
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
    await page.close()
    results.append(entry)
    ov = entry.get("dom", {}).get("horizontalOverflow")
    print(
        f"  {vp_name:<7} {page_path:<36} settle={entry.get('settleMs')}ms "
        f"api={entry.get('apiCallCount')} dup={len(entry.get('apiDuplicates') or {})} "
        f"hscroll={ov} small={entry.get('dom', {}).get('smallTargetCount')} "
        f"contrastFail={entry.get('dom', {}).get('contrastFailCount')}",
        flush=True,
    )


async def main():
    secret = (
        open(
            "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt"
        )
        .read()
        .strip()
    )
    import urllib.request

    req = urllib.request.Request(
        BACKEND + "/api/test/create-session",
        method="POST",
        headers={"Authorization": "Bearer " + secret},
    )
    with urllib.request.urlopen(req) as r:
        cookie_hdr = r.headers.get_all("Set-Cookie") or []
        r.read()
    cookies = []
    for h in cookie_hdr:
        nv = h.split(";")[0]
        name, _, val = nv.partition("=")
        cookies.append(
            {"name": name.strip(), "value": val.strip(), "domain": "127.0.0.1", "path": "/"}
        )
    print("cookies:", [c["name"] for c in cookies])

    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for vp_name, (w, h) in VIEWPORTS.items():
            ctx = await browser.new_context(
                viewport={"width": w, "height": h},
                is_mobile=(vp_name == "mobile"),
                has_touch=(vp_name == "mobile"),
                device_scale_factor=2 if vp_name == "mobile" else 1,
            )
            await ctx.add_cookies(cookies)

            async def route(r):
                u = r.request.url
                if "/api/" in u and u.startswith(FRONT):
                    await r.continue_(url=u.replace(FRONT, BACKEND))
                else:
                    await r.continue_()

            await ctx.route("**/*", route)
            print(f"== {vp_name} ==", flush=True)
            for p in PAGES:
                await probe(p, vp_name, ctx, results)
            await ctx.close()
        await browser.close()
    out = sys.argv[1]
    with open(out, "w") as f:
        json.dump(results, f, indent=1)
    print("wrote", out)


asyncio.run(main())

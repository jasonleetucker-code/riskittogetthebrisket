/**
 * The sitemap may not advertise a private route.
 *
 * W1-13 (public/private leakage audit, 2026-09-05). `public-routes.js` says
 * in its own docstring that it exists because three consumers — middleware,
 * the app shell and robots.txt — used to disagree about which pages need a
 * session. The sitemap was a FOURTH consumer that was never wired to it,
 * and it had drifted the same way: `/trades` was listed there while
 * `public-routes.js` declares it private and production redirects an
 * anonymous visitor to `/login?next=%2Ftrades`.
 *
 * Nothing leaked — robots.txt serves `Disallow: /` and allows only `/`,
 * `/login` and `/league` — but a sitemap is a positive assertion that a URL
 * is worth indexing, it is submitted to search engines, and it contradicted
 * robots.txt on the same host.
 *
 * This is a structural test on purpose: the drift is a one-line addition to
 * an array, which is invisible in review.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { isPublicPath } from "@/lib/public-routes";

vi.mock("../lib/server-backend.js", () => ({
  // No backend in a unit test: the sitemap's documented fallback is the
  // static routes only, which is exactly what this test wants to inspect.
  fetchBackendJson: vi.fn(async () => null),
}));

let sitemap;

beforeEach(async () => {
  vi.resetModules();
  ({ default: sitemap } = await import("@/app/sitemap.js"));
});

afterEach(() => {
  vi.restoreAllMocks();
});

function pathsOf(entries, origin = "https://chaseupside.com") {
  return entries.map((e) => e.url.replace(origin, ""));
}

describe("sitemap.xml", () => {
  it("lists no route that public-routes.js calls private", async () => {
    const entries = await sitemap();
    const offenders = pathsOf(entries).filter((p) => !isPublicPath(p.split("?")[0]));
    expect(offenders).toEqual([]);
  });

  it("no longer advertises /trades", async () => {
    // The specific drift this test was written for.
    const entries = await sitemap();
    expect(pathsOf(entries)).not.toContain("/trades");
  });

  it("still advertises the genuinely public routes", async () => {
    // A filter that emptied the sitemap would pass the first two
    // assertions vacuously.
    const paths = pathsOf(await sitemap());
    expect(paths).toContain("/");
    expect(paths).toContain("/league");
    expect(paths).toContain("/draft-capital");
    expect(paths.filter((p) => p.startsWith("/league?tab=")).length).toBeGreaterThan(5);
  });
});

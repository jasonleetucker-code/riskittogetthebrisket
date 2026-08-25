/**
 * V1-131 — the full chain, end to end.
 *
 *   canonical feature state
 *     -> /api/auth/status  (features.consensusEdge.available)
 *     -> useAuth
 *     -> nav model / filter
 *     -> RENDERED navigation
 *
 * The backend half of this chain is pinned in
 * `tests/api/test_nav_gated_features.py` — including the part that
 * matters most, that `available` tracks
 * `src.consensus_edge.api.is_available` (flag AND a loaded contract)
 * rather than the flag alone, in all four combinations.
 * `nav-capability-gating.test.js` pins the pure model filter.
 *
 * What NEITHER of those covers, and this file does: the two links
 * between them. `useAuth` must only ever publish an AUTHORITATIVE
 * capability, and the rendered chrome must actually stop drawing the
 * link. A model that filters correctly while `TopBar` renders from
 * something else would satisfy every other test here and still ship the
 * defect.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";

let pathname = "/rankings";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/TeamSwitcher", () => ({
  default: () => <span data-testid="team-switcher" />,
}));
vi.mock("@/components/LeagueSwitcher", () => ({
  default: () => <span data-testid="league-switcher" />,
}));

import TopBar from "@/components/shell/TopBar";
import { useAuth } from "@/components/useAuth";
import { isPublicPath } from "@/lib/public-routes";

const AVAILABLE = { consensusEdge: { available: true } };
const UNAVAILABLE = { consensusEdge: { available: false } };

function authStatusBody(features) {
  const body = { authenticated: true, username: "tester", isAdmin: false };
  if (features !== undefined) body.features = features;
  return body;
}

/** Stub /api/auth/status; everything else 404s so a stray call is loud. */
function stubAuthStatus(body, { ok = true } = {}) {
  const fetchMock = vi.fn((input) => {
    const url = String(input?.url || input);
    if (url.includes("/api/auth/status")) {
      return Promise.resolve({
        ok,
        status: ok ? 200 : 503,
        json: async () => body,
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  pathname = "/rankings";
  try {
    sessionStorage.clear();
  } catch {
    /* locked-down storage — the hook tolerates it, so must the test */
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ── link 1: /api/auth/status -> useAuth ──────────────────────────────

describe("useAuth publishes only an authoritative capability", () => {
  it("passes the server's capability block through unchanged", async () => {
    stubAuthStatus(authStatusBody(AVAILABLE));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.authenticated).toBe(true));
    expect(result.current.features).toEqual(AVAILABLE);
  });

  it("publishes an explicit unavailable as-is", async () => {
    stubAuthStatus(authStatusBody(UNAVAILABLE));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.authenticated).toBe(true));
    expect(result.current.features).toEqual(UNAVAILABLE);
  });

  it("yields null when the response carries NO features block", async () => {
    // An older or degraded backend. Null is the honest answer — the nav
    // filter reads it as "do not offer", which is the fail-closed
    // behaviour the truth table requires.
    stubAuthStatus(authStatusBody(undefined));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.authenticated).toBe(true));
    expect(result.current.features).toBeNull();
  });

  it("never adopts capabilities from a NON-authoritative response", async () => {
    // A 503 is not an answer about this user or this feature. Adopting a
    // capability from it would let a transient blip turn the nav on.
    stubAuthStatus(authStatusBody(AVAILABLE), { ok: false });
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.checking).toBe(false));
    expect(result.current.features).toBeNull();
  });

  it("drops capabilities on logout", async () => {
    stubAuthStatus(authStatusBody(AVAILABLE));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.features).toEqual(AVAILABLE));
    // jsdom cannot navigate; the state change is what is under test.
    delete window.location;
    window.location = { href: "" };
    await act(async () => {
      await result.current.logout();
    });
    expect(result.current.features).toBeNull();
  });
});

// ── link 2: nav model -> RENDERED navigation ─────────────────────────

function renderTopBar(capabilities) {
  return render(
    <TopBar
      authenticated
      isAdmin={false}
      capabilities={capabilities}
      isPublic={isPublicPath}
      onSearch={() => {}}
      onLogout={() => {}}
    />,
  );
}

/** Every href the rendered chrome offers, menus expanded or not. */
function renderedHrefs() {
  return Array.from(
    document.querySelectorAll("a[href], [role='menuitem']"),
  ).map((el) => el.getAttribute("href"));
}

/**
 * Render, then OPEN the group the gated item lives in.
 *
 * This is load-bearing, and the first version of this file got it
 * wrong. `NavMenu` renders its items only while `open` (`{open ? …}`),
 * so a "the link is absent" assertion taken against a collapsed menu is
 * true no matter what the capability says. Measured: mutating
 * `itemIsOffered` to `!== false` — breaking fail-closed outright — left
 * both negative tests here GREEN while the pure-model suite went 6 RED.
 * A negative assertion that cannot fail is not evidence.
 */
async function renderTopBarWithMarketOpen(capabilities) {
  const user = (await import("@testing-library/user-event")).default;
  const rendered = renderTopBar(capabilities);
  await user.click(screen.getByRole("button", { name: "Market menu" }));
  return rendered;
}

describe("rendered navigation honours the capability", () => {
  it("does NOT render the Consensus Edge link when it is unavailable", async () => {
    await renderTopBarWithMarketOpen(UNAVAILABLE);
    expect(renderedHrefs()).not.toContain("/consensus-edge");
    // The rest of the Market group must survive — gating one item is not
    // permission to drop its neighbours. Asserted on the OPEN menu, so
    // this also proves the absence above was measured against a menu
    // that was actually showing its items.
    expect(renderedHrefs()).toContain("/edge");
    expect(
      screen.getByRole("button", { name: "Market menu" }),
    ).toBeInTheDocument();
  });

  it("does NOT render it when the capability is unknown (null / missing / bare)", async () => {
    for (const caps of [
      null,
      undefined,
      {},
      { consensusEdge: {} },
      { consensusEdge: true },
    ]) {
      const { unmount } = await renderTopBarWithMarketOpen(caps);
      const hrefs = renderedHrefs();
      expect(hrefs, `capability ${JSON.stringify(caps)}`).not.toContain(
        "/consensus-edge",
      );
      // Same non-vacuity guard: the menu really is open.
      expect(hrefs, `capability ${JSON.stringify(caps)}`).toContain(
        "/edge",
      );
      unmount();
    }
  });

  it("renders it once the capability is explicitly available", async () => {
    await renderTopBarWithMarketOpen(AVAILABLE);
    expect(renderedHrefs()).toContain("/consensus-edge");
  });

  it("keeps every ungated destination regardless of the capability", () => {
    renderTopBar(null);
    for (const href of ["/rankings", "/trade", "/rosters", "/news"]) {
      expect(renderedHrefs()).toContain(href);
    }
  });
});

// ── the request budget: no second shell probe ────────────────────────

describe("no additional shell-level request was introduced", () => {
  it("the shell never fetches a Consensus Edge endpoint", async () => {
    // V1-108 ("non-data routes stop fetching the contract") is VERIFIED,
    // and the reason this capability rides /api/auth/status at all is
    // that a second per-page probe would erode it. A structural check,
    // because a runtime one would only catch the routes it happened to
    // exercise.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const url = await import("node:url");
    const root = path.resolve(
      path.dirname(url.fileURLToPath(import.meta.url)),
      "../../..",
    );
    const dirs = [
      "components/shell",
      "app/AppShellWrapper.jsx",
      "components/useAuth.js",
    ];
    const offenders = [];
    const walk = (p) => {
      const st = fs.statSync(p);
      if (st.isDirectory()) {
        for (const f of fs.readdirSync(p)) walk(path.join(p, f));
        return;
      }
      if (!/\.(jsx?|tsx?)$/.test(p)) return;
      const src = fs.readFileSync(p, "utf8");
      if (/(fetch|axios)\s*\(\s*[`'"][^`'"]*\/api\/consensus-edge/.test(src)) {
        offenders.push(path.relative(root, p));
      }
    };
    for (const d of dirs) walk(path.join(root, d));
    expect(
      offenders,
      `Shell modules must not probe Consensus Edge directly: ${offenders.join(", ")}`,
    ).toEqual([]);
  });
});

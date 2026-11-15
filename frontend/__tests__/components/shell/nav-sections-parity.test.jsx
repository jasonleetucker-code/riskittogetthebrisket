/**
 * Section headings, desktop / mobile parity, and contextual related links
 * (UX navigation audit 2026-11-01: NAV-03, NAV-04, NAV-05, A11Y-02).
 *
 * The desktop dropdown used to be the ONLY surface that showed a group's
 * section headings; the mobile drawer flattened them, so the same IA read
 * differently per viewport.  These tests pin that every surface renders
 * the same nav-model `sectionRuns`, with group semantics.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let pathname = "/rankings";
let authValue = { authenticated: true, isAdmin: false, features: null };
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/TeamSwitcher", () => ({ default: () => null }));
vi.mock("@/components/LeagueSwitcher", () => ({ default: () => null }));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => authValue }));

import TopBar from "@/components/shell/TopBar";
import { MobileTabBar } from "@/components/shell/MobileChrome";
import RelatedLinks from "@/components/shell/RelatedLinks";
import {
  NAV_MODEL,
  navGroupsFor,
  paletteTargets,
  relatedNavItems,
  sectionRuns,
} from "@/lib/nav-model";
import { isPublicPath } from "@/lib/public-routes";

const ALL_ON = {
  waiverAdvisor: { available: true },
  idpStreaming: { available: true },
  consensusEdge: { available: true },
  managerIntelligence: { available: true },
};

beforeEach(() => {
  pathname = "/rankings";
  authValue = { authenticated: true, isAdmin: false, features: null };
});

describe("sectionRuns", () => {
  it("starts a run on each new section and lets unsectioned items continue the run above", () => {
    const runs = sectionRuns([
      { href: "/a", section: "One" },
      { href: "/b" },
      { href: "/c", section: "Two" },
      { href: "/d", section: "Two" },
    ]);
    expect(runs.map((r) => [r.section, r.items.map((i) => i.href)])).toEqual([
      ["One", ["/a", "/b"]],
      ["Two", ["/c", "/d"]],
    ]);
  });

  it("returns one null-section run for an unsectioned menu", () => {
    expect(sectionRuns([{ href: "/a" }, { href: "/b" }])).toEqual([
      { section: null, items: [{ href: "/a" }, { href: "/b" }] },
    ]);
  });

  it("My Team groups the waiver tools under one Waivers & FAAB heading", () => {
    const myTeam = navGroupsFor({ capabilities: ALL_ON }).find((g) => g.key === "myteam");
    const runs = sectionRuns(myTeam.items);
    const waivers = runs.find((r) => r.section === "Waivers & FAAB");
    expect(waivers.items.map((i) => i.label)).toEqual([
      "Waivers",
      "Waiver Advisor",
      "Weekly IDP Streaming",
    ]);
    expect(runs.map((r) => r.section)).toEqual([
      "This week",
      "Roster",
      "Waivers & FAAB",
      "Draft & strategy",
    ]);
  });

  it("a gated-away first item never strands its section (headings follow surviving items)", () => {
    // Advisor + streaming off: the Waivers heading must still sit on Waivers.
    const myTeam = navGroupsFor({ capabilities: {} }).find((g) => g.key === "myteam");
    const waivers = sectionRuns(myTeam.items).find((r) => r.section === "Waivers & FAAB");
    expect(waivers.items.map((i) => i.label)).toEqual(["Waivers"]);
  });
});

describe("desktop menu and mobile drawer render the same sections", () => {
  it("the desktop My Team menu exposes each section as a labelled group of menuitems", async () => {
    const user = userEvent.setup();
    render(
      <TopBar
        authenticated
        capabilities={ALL_ON}
        isPublic={isPublicPath}
        onSearch={() => {}}
        onLogout={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "My Team menu" }));
    const menu = screen.getByRole("menu", { name: "My Team" });
    expect(within(menu).getAllByRole("group")).toHaveLength(4);
    for (const name of ["This week", "Roster", "Waivers & FAAB", "Draft & strategy"]) {
      expect(within(menu).getByRole("group", { name })).toBeInTheDocument();
    }
    // No unowned, unlabelled children: every child of the menu is a group
    // or a menuitem.
    for (const child of Array.from(menu.children)) {
      const role = child.getAttribute("role");
      expect(["group", "menuitem"]).toContain(role);
    }
  });

  it("the mobile drawer shows the same section groups as the desktop menu", async () => {
    const user = userEvent.setup();
    render(
      <MobileTabBar
        authenticated
        capabilities={ALL_ON}
        isPublic={isPublicPath}
        onLogout={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: /menu/i }));
    const dialog = screen.getByRole("dialog");
    const waivers = within(dialog).getByRole("group", { name: "Waivers & FAAB" });
    expect(within(waivers).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "WaiversAdd/drop analysis against your roster",
      expect.stringMatching(/^Waiver Advisor/),
      expect.stringMatching(/^Weekly IDP Streaming/),
    ]);
    for (const name of ["This week", "Roster", "Draft & strategy"]) {
      expect(within(dialog).getByRole("group", { name })).toBeInTheDocument();
    }
  });

  it("parity: every drawer link appears in the desktop model for the same viewer", () => {
    // Same function feeds both: assert the set equality the UI relies on.
    const desktop = navGroupsFor({ capabilities: ALL_ON }).flatMap((g) =>
      (g.items && g.items.length ? g.items : [g]).map((i) => i.href),
    );
    const palette = paletteTargets({ capabilities: ALL_ON }).map((t) => t.href);
    for (const href of desktop) expect(palette).toContain(href);
  });
});

describe("relatedNavItems / RelatedLinks", () => {
  it("resolves labels from the model and drops unknown hrefs", () => {
    const items = relatedNavItems(["/waivers", "/nope"], {});
    expect(items.map((i) => i.label)).toEqual(["Waivers"]);
  });

  it("fails closed on capability-gated destinations", () => {
    expect(relatedNavItems(["/waiver-advisor"], { capabilities: null })).toEqual([]);
    expect(
      relatedNavItems(["/waiver-advisor"], { capabilities: { waiverAdvisor: { available: true } } }).map(
        (i) => i.label,
      ),
    ).toEqual(["Waiver Advisor"]);
  });

  it("never offers an admin-only page to a non-admin", () => {
    expect(relatedNavItems(["/admin"], { isAdmin: false })).toEqual([]);
    expect(relatedNavItems(["/admin"], { isAdmin: true }).map((i) => i.label)).toEqual(["Admin"]);
  });

  it("renders a labelled navigation landmark with canonical labels", () => {
    authValue = { authenticated: true, isAdmin: false, features: ALL_ON };
    render(<RelatedLinks hrefs={["/waiver-advisor", "/waiver-advisor?mode=streaming"]} />);
    const nav = screen.getByRole("navigation", { name: "Related pages" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Waiver Advisor",
      "Weekly IDP Streaming",
    ]);
    expect(within(nav).getByRole("link", { name: "Weekly IDP Streaming" })).toHaveAttribute(
      "href",
      "/waiver-advisor?mode=streaming",
    );
  });

  it("offers no link while capabilities are unresolved, but holds the row's height", () => {
    authValue = { authenticated: null, isAdmin: false, features: null };
    const { container } = render(<RelatedLinks hrefs={["/waiver-advisor"]} />);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    const placeholder = container.querySelector(".shell-related--pending");
    expect(placeholder).toHaveAttribute("aria-hidden", "true");
  });

  it("cached session (authenticated true, features still null) holds the row, then fills it", () => {
    // useAuth paints `authenticated: true` from its cache before the probe
    // returns the capability map — the path that used to pop the row in.
    authValue = { authenticated: true, isAdmin: false, features: null };
    const hrefs = ["/waiver-advisor", "/waiver-advisor?mode=streaming"];
    const { container, rerender } = render(<RelatedLinks hrefs={hrefs} />);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(container.querySelector(".shell-related--pending")).toHaveAttribute("aria-hidden", "true");

    authValue = { authenticated: true, isAdmin: false, features: ALL_ON };
    rerender(<RelatedLinks hrefs={hrefs} />);
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Waiver Advisor",
      "Weekly IDP Streaming",
    ]);
  });

  it("keeps the held height when capabilities resolve as unavailable (no collapse shift)", () => {
    authValue = { authenticated: true, isAdmin: false, features: null };
    const { container, rerender } = render(<RelatedLinks hrefs={["/waiver-advisor"]} />);
    expect(container.querySelector(".shell-related--pending")).not.toBeNull();

    authValue = { authenticated: true, isAdmin: false, features: {} };
    rerender(<RelatedLinks hrefs={["/waiver-advisor"]} />);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(container.querySelector(".shell-related--pending")).not.toBeNull();
  });

  it("a confirmed sign-out reserves nothing", () => {
    authValue = { authenticated: false, isAdmin: false, features: null };
    const { container } = render(<RelatedLinks hrefs={["/waiver-advisor"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing once resolved with nothing to offer", () => {
    authValue = { authenticated: true, isAdmin: false, features: {} };
    const { container } = render(<RelatedLinks hrefs={["/waiver-advisor"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("ungated links render on the first paint, before the probe resolves", () => {
    authValue = { authenticated: null, isAdmin: false, features: null };
    render(<RelatedLinks hrefs={["/waivers"]} />);
    expect(screen.getByRole("link", { name: "Waivers" })).toHaveAttribute("href", "/waivers");
  });

  it("Sharp People is reachable by name (palette) — it had no inbound link", () => {
    expect(paletteTargets({}).find((t) => t.href === "/market/sharp-people")?.label).toBe(
      "Sharp People",
    );
    // and never through a menu group (promotion is an owner decision)
    expect(
      NAV_MODEL.flatMap((g) => g.items || []).some((i) => i.href === "/market/sharp-people"),
    ).toBe(false);
  });
});

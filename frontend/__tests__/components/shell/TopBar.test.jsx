/**
 * TopBar / MobileChrome a11y + gating spec — landmarks, aria-current,
 * button-triggered menus, public-route filtering.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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
import { MobileTabBar } from "@/components/shell/MobileChrome";

const PUBLIC_ROUTES = new Set(["/", "/login", "/draft-capital", "/trades", "/league"]);
const isPublic = (href) => PUBLIC_ROUTES.has(href);

beforeEach(() => {
  pathname = "/rankings";
});

describe("TopBar landmarks + active state", () => {
  it("renders a labelled primary navigation landmark inside a banner", () => {
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
  });

  it("stamps aria-current on the active direct link only", () => {
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    const rankings = screen.getByRole("link", { name: "Rankings" });
    expect(rankings).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "News" })).not.toHaveAttribute("aria-current");
  });

  it("group menus open from a BUTTON trigger (click), list menuitems, and mark the current route", async () => {
    pathname = "/arbitrage";
    const user = userEvent.setup();
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    const trigger = screen.getByRole("button", { name: "Trade" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Trade" });
    const finder = within(menu).getByRole("menuitem", { name: /Arbitrage Finder/ });
    expect(finder).toHaveAttribute("aria-current", "page");
    expect(
      within(menu).getByRole("menuitem", { name: /Calculator/ })
    ).not.toHaveAttribute("aria-current");
  });

  it("Escape closes an open menu and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    const trigger = screen.getByRole("button", { name: "Intel" });
    await user.click(trigger);
    expect(screen.getByRole("menu", { name: "Intel" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu", { name: "Intel" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("System menu contains settings, ops surfaces, and sign out", async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={onLogout} />
    );
    await user.click(screen.getByRole("button", { name: "System" }));
    const menu = screen.getByRole("menu", { name: "System" });
    expect(within(menu).getByRole("menuitem", { name: /Settings/ })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Admin/ })).toBeInTheDocument();
    await user.click(within(menu).getByRole("menuitem", { name: "Sign out" }));
    expect(onLogout).toHaveBeenCalled();
  });
});

describe("auth gating (PUBLIC_ROUTES semantics preserved)", () => {
  it("unauthenticated visitors see only public destinations plus Login", () => {
    render(
      <TopBar
        authenticated={false}
        isPublic={isPublic}
        onSearch={() => {}}
        onLogout={() => {}}
      />
    );
    // public: League group (its /league children) + Trade group filtered to /trades
    expect(screen.queryByRole("link", { name: "Rankings" })).toBeNull();
    expect(screen.queryByRole("link", { name: "News" })).toBeNull();
    expect(screen.getByRole("link", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "League" })).toBeInTheDocument();
    // no switchers, no search, no System menu when logged out
    expect(screen.queryByTestId("team-switcher")).toBeNull();
    expect(screen.queryByRole("button", { name: "System" })).toBeNull();
  });

  it("renders NO nav items while auth is unresolved, and the banner/landmark anyway", () => {
    // ``authenticated === null`` means "not answered yet", which is NOT
    // the same as "signed out".  Answering it with the public subset
    // made every signed-in first paint render a 2-item nav and then
    // INSERT four more, sliding the surviving items sideways — a shift
    // on every route, since this is the shell.  Reserve-by-absence is
    // free here: the nav sits between a left-aligned brand and a
    // ``margin-left: auto`` rail, so items appear without moving
    // either neighbour.
    for (const unresolved of [null, undefined]) {
      const { unmount } = render(
        <TopBar
          authenticated={unresolved}
          isPublic={isPublic}
          onSearch={() => {}}
          onLogout={() => {}}
        />
      );
      const nav = screen.getByRole("navigation", { name: "Primary" });
      expect(within(nav).queryAllByRole("link")).toHaveLength(0);
      expect(within(nav).queryAllByRole("button")).toHaveLength(0);
      // and nothing from the signed-out branch leaks in either
      expect(screen.queryByRole("link", { name: "Login" })).toBeNull();
      expect(screen.queryByTestId("team-switcher")).toBeNull();
      unmount();
    }
  });

  it("authenticated users get switchers + search + System", () => {
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    expect(screen.getByTestId("team-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("league-switcher")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Search/ })).toBeInTheDocument();
  });
});

describe("MobileTabBar", () => {
  it("renders the tabs + a Menu button that opens the full-IA drawer", async () => {
    const user = userEvent.setup();
    render(
      <MobileTabBar authenticated isPublic={isPublic} onLogout={() => {}} />
    );
    expect(screen.getByRole("link", { name: /Ranks/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
    const menuBtn = screen.getByRole("button", { name: /Menu/ });
    expect(menuBtn).toHaveAttribute("aria-haspopup", "dialog");
    await user.click(menuBtn);
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    // full IA present: a Trade group item and a System entry
    expect(within(drawer).getByText("Arbitrage Finder")).toBeInTheDocument();
    expect(within(drawer).getByText("Settings")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("longest-prefix tab activation: /trade lights Trade, not Home", () => {
    pathname = "/trade";
    render(
      <MobileTabBar authenticated isPublic={isPublic} onLogout={() => {}} />
    );
    expect(screen.getByRole("link", { name: /Trade/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(screen.getByRole("link", { name: /Home/ })).not.toHaveAttribute(
      "aria-current"
    );
  });
});

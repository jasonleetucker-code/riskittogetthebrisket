/**
 * TopBar / MobileChrome a11y + gating spec — landmarks, aria-current,
 * the split group trigger, public-route filtering, admin gating.
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
// The real predicate, not a local copy — a stale duplicate here is how
// the shell and the middleware drifted apart in the first place.
import { isPublicPath } from "@/lib/public-routes";

const isPublic = isPublicPath;

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

  it("stamps aria-current on the active group link only", () => {
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    expect(screen.getByRole("link", { name: "Rankings" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(screen.getByRole("link", { name: "News" })).not.toHaveAttribute("aria-current");
  });

  it("a group label is a LINK to the group's primary page", async () => {
    // The whole trigger used to be one button, so top-level labels
    // were signposts you could not walk through.  Clicking "Trades"
    // must land on the calculator, not merely open a list.
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    expect(screen.getByRole("link", { name: "Trades" })).toHaveAttribute("href", "/trade");
    expect(screen.getByRole("link", { name: "My Team" })).toHaveAttribute("href", "/rosters");
    expect(screen.getByRole("link", { name: "Rankings" })).toHaveAttribute("href", "/rankings");
  });

  it("the caret button opens the menu, lists menuitems, and marks the current route", async () => {
    pathname = "/arbitrage";
    const user = userEvent.setup();
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    const trigger = screen.getByRole("button", { name: "Trades menu" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Trades" });
    expect(within(menu).getByRole("menuitem", { name: /Arbitrage/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(
      within(menu).getByRole("menuitem", { name: /Trade Calculator/ })
    ).not.toHaveAttribute("aria-current");
  });

  it("Escape closes an open menu and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    const trigger = screen.getByRole("button", { name: "Market menu" });
    await user.click(trigger);
    expect(screen.getByRole("menu", { name: "Market" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu", { name: "Market" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("System menu shows ops surfaces to an admin, with sign out", async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();
    render(
      <TopBar
        authenticated
        isAdmin
        isPublic={isPublic}
        onSearch={() => {}}
        onLogout={onLogout}
      />
    );
    await user.click(screen.getByRole("button", { name: "System menu" }));
    const menu = screen.getByRole("menu", { name: "System" });
    expect(within(menu).getByRole("menuitem", { name: /Settings/ })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Admin/ })).toBeInTheDocument();
    await user.click(within(menu).getByRole("menuitem", { name: "Sign out" }));
    expect(onLogout).toHaveBeenCalled();
  });

  it("System menu hides ops surfaces from a non-admin", async () => {
    // The server has always 403'd these; offering a door that is
    // always locked is worse than not showing the door.
    const user = userEvent.setup();
    render(
      <TopBar authenticated isPublic={isPublic} onSearch={() => {}} onLogout={() => {}} />
    );
    await user.click(screen.getByRole("button", { name: "System menu" }));
    const menu = screen.getByRole("menu", { name: "System" });
    expect(within(menu).getByRole("menuitem", { name: /Settings/ })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: /Admin/ })).toBeNull();
    expect(within(menu).queryByRole("menuitem", { name: /Source Health/ })).toBeNull();
  });
});

describe("auth gating", () => {
  it("unauthenticated visitors see only public destinations plus Sign in", () => {
    render(
      <TopBar
        authenticated={false}
        isPublic={isPublic}
        onSearch={() => {}}
        onLogout={() => {}}
      />
    );
    expect(screen.queryByRole("link", { name: "Rankings" })).toBeNull();
    expect(screen.queryByRole("link", { name: "News" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Trades" })).toBeNull();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    // League survives: its Hub + Activity children are genuinely public.
    expect(screen.getByRole("link", { name: "League" })).toBeInTheDocument();
    // no switchers, no search, no System menu when logged out
    expect(screen.queryByTestId("team-switcher")).toBeNull();
    expect(screen.queryByRole("button", { name: "System menu" })).toBeNull();
  });

  it("the logged-out League menu offers only its public children", async () => {
    const user = userEvent.setup();
    render(
      <TopBar
        authenticated={false}
        isPublic={isPublic}
        onSearch={() => {}}
        onLogout={() => {}}
      />
    );
    await user.click(screen.getByRole("button", { name: "League menu" }));
    const menu = screen.getByRole("menu", { name: "League" });
    expect(within(menu).getByRole("menuitem", { name: /Hub/ })).toBeInTheDocument();
    // /league/activity is public and must appear — the old exact-match
    // route set hid it from logged-out visitors.
    expect(within(menu).getByRole("menuitem", { name: /Activity/ })).toBeInTheDocument();
    // Scoring Comparison is private and must not.
    expect(
      within(menu).queryByRole("menuitem", { name: /Scoring Comparison/ })
    ).toBeNull();
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
    render(<MobileTabBar authenticated isAdmin isPublic={isPublic} onLogout={() => {}} />);
    expect(screen.getByRole("link", { name: /Ranks/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
    const menuBtn = screen.getByRole("button", { name: /Menu/ });
    expect(menuBtn).toHaveAttribute("aria-haspopup", "dialog");
    await user.click(menuBtn);
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    // full IA present: a Trades group item and a System entry
    expect(within(drawer).getByText("Arbitrage")).toBeInTheDocument();
    expect(within(drawer).getByText("Settings")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("hides ops surfaces in the drawer from a non-admin", async () => {
    const user = userEvent.setup();
    render(<MobileTabBar authenticated isPublic={isPublic} onLogout={() => {}} />);
    await user.click(screen.getByRole("button", { name: /Menu/ }));
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    expect(within(drawer).getByText("Settings")).toBeInTheDocument();
    expect(within(drawer).queryByText("Admin")).toBeNull();
  });

  it("longest-prefix tab activation: /trade lights Trade, not Home", () => {
    pathname = "/trade";
    render(<MobileTabBar authenticated isPublic={isPublic} onLogout={() => {}} />);
    expect(screen.getByRole("link", { name: /Trade/ })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(screen.getByRole("link", { name: /Home/ })).not.toHaveAttribute("aria-current");
  });

  it("logged-out mobile offers League and a Sign in tab", () => {
    // Filtering the authed tabs by "is public" left Home + Menu and no
    // route to /login anywhere in the mobile chrome.
    pathname = "/";
    render(
      <MobileTabBar authenticated={false} isPublic={isPublic} onLogout={() => {}} />
    );
    expect(screen.getByRole("link", { name: /Sign in/ })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: /League/ })).toHaveAttribute("href", "/league");
    expect(screen.queryByRole("link", { name: /Ranks/ })).toBeNull();
  });
});

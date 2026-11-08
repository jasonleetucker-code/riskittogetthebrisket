import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

let pathname = "/players/demo-01";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/components/TeamSwitcher", () => ({
  default: () => <button>Selected team</button>,
}));
vi.mock("@/components/LeagueSwitcher", () => ({
  default: () => <button>Selected league</button>,
}));

import TopBar from "@/components/shell/TopBar";
import { MobileTopBar } from "@/components/shell/MobileChrome";
import { isPublicPath } from "@/lib/public-routes";

beforeEach(() => {
  pathname = "/players/demo-01";
});

describe("Sports Network shell identity and task continuity", () => {
  it("gives the desktop wordmark a single accessible home link", () => {
    render(<TopBar authenticated={false} isPublic={isPublicPath} />);
    const brand = screen.getByRole("link", {
      name: "Chase Upside",
      exact: true,
    });
    expect(brand).toHaveAttribute("href", "/");
    expect(
      screen.getAllByRole("link", { name: "Chase Upside", exact: true }),
    ).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(screen.queryByRole("button", { name: "Selected team" })).toBeNull();
  });

  it("keeps mobile identity, current-route orientation and real research actions together", async () => {
    pathname = "/rankings";
    const onSearch = vi.fn();
    render(<MobileTopBar authenticated onSearch={onSearch} searchEnabled />);
    expect(
      screen.getByRole("link", { name: "Chase Upside", exact: true }),
    ).toHaveAttribute("href", "/");
    expect(screen.getByText("Rankings")).toBeVisible();
    expect(screen.getByRole("button", { name: "Selected team" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Selected league" }),
    ).toBeVisible();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Search", exact: true }));
    expect(onSearch).toHaveBeenCalledTimes(1);
  });

  it("does not turn unresolved auth or unavailable search into an offer", () => {
    render(
      <MobileTopBar
        authenticated={null}
        onSearch={vi.fn()}
        searchEnabled={false}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Chase Upside", exact: true }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Search", exact: true }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Selected team" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Selected league" }),
    ).toBeNull();
  });

  it("opens a closed group with arrow keys and places focus at the requested end", async () => {
    const user = userEvent.setup();
    render(<TopBar authenticated isPublic={isPublicPath} />);
    const trigger = screen.getByRole("button", { name: "Rankings menu" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    let menu = screen.getByRole("menu", { name: "Rankings" });
    await waitFor(() =>
      expect(within(menu).getAllByRole("menuitem")[0]).toHaveFocus(),
    );
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    menu = screen.getByRole("menu", { name: "Rankings" });
    await waitFor(() =>
      expect(within(menu).getAllByRole("menuitem").at(-1)).toHaveFocus(),
    );
  });
});

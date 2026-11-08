import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";

const state = vi.hoisted(() => ({ authenticated: false, search: "" }));
vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => ({ authenticated: state.authenticated }),
}));
vi.mock("@/components/terminal/TerminalLayout", () => ({
  default: () => <div data-testid="private-dashboard" />,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("next/dynamic", () => ({ default: () => () => <div /> }));
vi.mock("@/app/league/shared.jsx", () => ({ buildManagerLookup: () => ({}) }));
vi.mock("@/app/league/sections/overview.jsx", () => ({
  default: () => <p>Actual public overview section</p>,
}));

import HomeClient from "@/app/HomeClient";
import LeagueClient from "@/app/league/LeagueClient";
import { visibleTabs } from "@/app/league/tabs";

beforeEach(() => {
  state.authenticated = false;
  state.search = "";
});

describe("Sports Network public entry and league frame", () => {
  it("keeps a canonical brand heading and the two real public/private destinations", () => {
    const { container } = render(<HomeClient advisorServed={false} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Chase Upside" }),
    ).toBeVisible();
    expect(
      [...container.querySelectorAll("a")].map((a) => a.getAttribute("href")),
    ).toEqual(["/league", "/login"]);
    expect(screen.getByText(/Members only: player rankings/)).toBeVisible();
    expect(screen.queryByText(/Brisket Trade Advisor/)).toBeNull();
  });

  it("advertises the advisor only when the server confirms it is served", () => {
    render(<HomeClient advisorServed />);
    expect(
      screen.getByRole("link", { name: "Go to League Hub" }),
    ).toHaveAttribute("href", "/league");
    expect(
      screen.getByText(/the Brisket Trade Advisor, plus champions/),
    ).toBeVisible();
  });

  it("leaves authenticated home on the actual private dashboard", () => {
    state.authenticated = true;
    render(<HomeClient />);
    expect(screen.getByTestId("private-dashboard")).toBeVisible();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Chase Upside" }),
    ).toBeNull();
  });

  it("uses the supplied league name and factual metadata without dropping sections", () => {
    render(
      <LeagueClient
        initialContract={{
          league: {
            leagueName: "Sample Public League",
            seasonsCovered: [2024, 2025, 2026],
            managers: [{ ownerId: "one" }, { ownerId: "two" }],
          },
          sections: { overview: {} },
        }}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Sample Public League" }),
    ).toBeVisible();
    const record = screen.getByRole("complementary", {
      name: "Public league record",
    });
    expect(within(record).getByText("2024, 2025, 2026")).toBeVisible();
    expect(within(record).getByText("2")).toBeVisible();
    expect(screen.getAllByRole("tab")).toHaveLength(
      visibleTabs({ advisorAvailable: false }).length,
    );
    expect(screen.getByText("Actual public overview section")).toBeVisible();
  });

  it("does not invent two seasons or zero managers when metadata are absent", () => {
    render(
      <LeagueClient
        initialContract={{
          league: { leagueName: "No coverage yet" },
          sections: { overview: {} },
        }}
      />,
    );
    const record = screen.getByRole("complementary", {
      name: "Public league record",
    });
    expect(within(record).getByText("Not yet available")).toBeVisible();
    expect(within(record).getByText("Unavailable")).toBeVisible();
    expect(screen.getByText(/Season coverage unavailable/)).toBeVisible();
    expect(screen.queryByText(/Last 2 dynasty seasons/)).toBeNull();
  });
});

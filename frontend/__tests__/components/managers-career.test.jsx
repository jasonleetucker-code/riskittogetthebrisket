import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CAREER, COMPARE } from "../fixtures/manager-intel-career";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/managers/compare",
  useSearchParams: () => new URLSearchParams(),
}));

import ManagerCareer from "@/app/managers/ManagerCareer";
import ComparePage from "@/app/managers/compare/page";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("Career tab (Batch E)", () => {
  it("renders seasons, totals with coverage and an unknown finish", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, CAREER));
    render(<ManagerCareer username="fan1" scope="dynasty" />);
    const table = await screen.findByRole("table", { name: /Every season this manager held/ });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/manager-intel/career?username=fan1",
      expect.objectContaining({ cache: "no-store" }),
    );
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2 held seasons; 2024 (not held) is absent
    expect(within(rows[2]).getByText("Unknown")).toBeTruthy();
    expect(within(rows[2]).queryByText(/Missed/)).toBeNull();
    expect(within(rows[1]).getByText(/season in progress/)).toBeTruthy();
    expect(screen.getByText("over 0 complete seasons")).toBeTruthy();
    // Chain and season coverage are named.
    expect(screen.getByText(/history stopped early/)).toBeTruthy();
    // Not-held seasons are listed as absent, never as losses.
    expect(screen.getByText("Seasons not held")).toBeTruthy();
  });

  it("opens an archetype chip's evidence drilldown", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, CAREER));
    const user = userEvent.setup();
    render(<ManagerCareer username="fan1" scope="dynasty" />);
    const chip = await screen.findByRole("button", { name: "Consolidator" });
    await user.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(/^Evidence suggests a consolidator/)).toBeTruthy();
    expect(screen.getByText("0.5 (PRIOR CONSOLIDATOR_SHARE_MIN)")).toBeTruthy();
    // An insufficient-sample archetype is never a chip.
    expect(screen.queryByRole("button", { name: "Pick hoarder" })).toBeNull();
  });

  it("shows the API's error message", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse(429, { error: "rate_limited", message: "Too many lookups." }),
    );
    render(<ManagerCareer username="fan1" scope="dynasty" />);
    expect(await screen.findByText("Too many lookups.")).toBeTruthy();
  });
});

describe("Compare page (Batch E)", () => {
  it("reads the query string, compares, and shows unavailable values as —", async () => {
    window.history.replaceState(null, "", "/managers/compare?a=fan1&b=fan2&league=99");
    global.fetch = vi.fn(async () => jsonResponse(200, COMPARE));
    render(<ComparePage />);
    const table = await screen.findByRole("table", { name: /FAN1 and FAN2 side by side/ });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/manager-intel/compare?a=fan1&b=fan2&leagueId=99",
      expect.objectContaining({ cache: "no-store" }),
    );
    const picks = within(table).getByRole("row", { name: /Draft picks held/ });
    expect(within(picks).getByText("14")).toBeTruthy();
    expect(within(picks).getByText("—")).toBeTruthy();
    expect(screen.getByText("Higher than 67% of the league")).toBeTruthy();
    expect(screen.getByText("pick ownership unknown")).toBeTruthy();
  });

  it("refuses to fetch without a second manager or league", async () => {
    global.fetch = vi.fn();
    const user = userEvent.setup();
    render(<ComparePage />);
    await user.type(screen.getByLabelText("Manager"), "fan1");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByText(/second manager or a league id/)).toBeTruthy();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

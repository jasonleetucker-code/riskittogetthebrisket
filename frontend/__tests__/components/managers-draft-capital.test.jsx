import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagersPage from "@/app/managers/page";
import { PROFILE } from "../fixtures/manager-intel-profile";
import { ACTIVITY } from "../fixtures/manager-intel-activity";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function routedFetch(activity = ACTIVITY) {
  return vi.fn(async (url) =>
    String(url).includes("/activity")
      ? jsonResponse(200, activity)
      : jsonResponse(200, PROFILE),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/managers");
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function lookUp(user) {
  await user.type(screen.getByLabelText("Sleeper username"), "dynastyfan");
  await user.click(screen.getByRole("button", { name: "Look up" }));
  await screen.findByRole("heading", { name: "Dynasty Fan" });
}

describe("Manager Intelligence draft capital + tendencies (B3)", () => {
  it("renders picks by league, the unavailable state and pick movement", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Draft capital" }));

    const table = await screen.findByRole("table", {
      name: "Picks held in Alpha Dynasty",
    });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4); // header + 3 picks
    expect(within(table).getByText("From Rival Two")).toBeTruthy();
    expect(within(table).getAllByText("3,500")).toHaveLength(2);
    expect(within(table).getByText("—")).toBeTruthy();
    expect(
      screen.getByText(
        "3 held · 1 acquired · 1 own traded away · value 7,000 · 1 unpriced",
      ),
    ).toBeTruthy();
    expect(screen.getByText(/2027 Round 2 \(now Rival Three\)/)).toBeTruthy();

    // The rate-limited league says its ownership is unknown — not "no picks".
    expect(
      screen.getByText(/Pick ownership unavailable — Sleeper rate-limited/),
    ).toBeTruthy();
    expect(screen.queryByText("Holds no picks")).toBeNull();
    expect(
      screen.queryByRole("table", { name: "Picks held in Beta League" }),
    ).toBeNull();

    // Pick movement.
    expect(
      screen.getByText(/2027 Round 1 \(3,500\) · from Rival Two · Still held/),
    ).toBeTruthy();
    // Coverage banner names the traded-picks gap's league.
    expect(
      screen.getByText(/Beta League: transactions partly read/),
    ).toBeTruthy();
  });

  it("shows the current-season-only state for an earlier season", async () => {
    global.fetch = routedFetch({
      ...ACTIVITY,
      draftCapital: { available: false, reason: "earlier_season", leagues: [] },
    });
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Draft capital" }));
    expect(await screen.findByText("Current season only")).toBeTruthy();
  });

  it("shows tendencies under Recent trades with samples and the insufficient state", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Recent trades" }));
    expect(
      await screen.findByRole("heading", { name: "Tendencies" }),
    ).toBeTruthy();
    expect(
      screen.getAllByText(
        "Insufficient sample — n = 2 trades (at least 3 needed) · last 30 days",
      ),
    ).toHaveLength(2);
    // Insufficient blocks list no counts.
    expect(screen.queryByRole("list", { name: "Picks vs players" })).toBeNull();
    const pos = screen.getByRole("table", {
      name: "Players acquired and sent by trade, by position.",
    });
    expect(within(pos).getByText("2 · 7,500")).toBeTruthy();
    expect(within(pos).getByText("2 · 4,000 (1 unpriced)")).toBeTruthy();
  });
});

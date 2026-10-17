import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagersPage from "@/app/managers/page";
import { PROFILE } from "../fixtures/manager-intel-profile";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/managers");
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function search(user, name = "dynastyfan") {
  await user.type(screen.getByLabelText("Sleeper username"), name);
  await user.click(screen.getByRole("button", { name: "Look up" }));
}

describe("Manager Intelligence page", () => {
  it("starts idle and does not fetch", () => {
    global.fetch = vi.fn();
    render(<ManagersPage />);
    expect(
      screen.getByRole("heading", { name: "Manager Intelligence" }),
    ).toBeTruthy();
    expect(screen.getByText("Look up a manager")).toBeTruthy();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("looks up a manager and renders the portfolio, with unpriced players as —", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, PROFILE));
    const user = userEvent.setup();
    render(<ManagersPage />);
    await search(user);
    await screen.findByRole("heading", { name: "Dynasty Fan" });
    expect(global.fetch.mock.calls[0][0]).toBe(
      "/api/manager-intel/profile?username=dynastyfan",
    );

    const table = screen.getByRole("table");
    const lbRow = within(table).getByText("Obscure Linebacker").closest("tr");
    expect(within(lbRow).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(lbRow).queryByText("0")).toBeNull();
    expect(within(table).getByText("2 / 2 (100%)")).toBeTruthy();
    expect(window.location.search).toBe("?username=dynastyfan");
    expect(
      JSON.parse(window.localStorage.getItem("managerIntel.recent")),
    ).toEqual(["dynastyfan"]);
  });

  it("expands a player to the leagues he is owned in", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, PROFILE));
    const user = userEvent.setup();
    render(<ManagersPage />);
    await search(user);
    await screen.findByRole("heading", { name: "Dynasty Fan" });
    await user.click(
      screen.getByRole("button", { name: "Show leagues for Justin Jefferson" }),
    );
    const list = screen.getByRole("list", {
      name: "Leagues for Justin Jefferson",
    });
    expect(within(list).getByText("Alpha Dynasty")).toBeTruthy();
    expect(within(list).getByText("Bench")).toBeTruthy();
  });

  it("filters by position", async () => {
    global.fetch = vi.fn(async () => jsonResponse(200, PROFILE));
    const user = userEvent.setup();
    render(<ManagersPage />);
    await search(user);
    await screen.findByRole("heading", { name: "Dynasty Fan" });
    await user.selectOptions(screen.getByLabelText("Position"), "LB");
    expect(screen.queryByText("Justin Jefferson")).toBeNull();
    expect(screen.getByText("1 of 2 players")).toBeTruthy();
  });

  it("names a partial answer instead of hiding it", async () => {
    const partial = {
      ...PROFILE,
      status: "partial",
      leaguesUnreadable: 1,
      leagues: [
        ...PROFILE.leagues,
        { leagueId: "L3", name: "Gamma", state: "unavailable", format: {} },
      ],
    };
    global.fetch = vi.fn(async () => jsonResponse(200, partial));
    const user = userEvent.setup();
    render(<ManagersPage />);
    await search(user);
    expect(
      await screen.findByText("Some leagues could not be read"),
    ).toBeTruthy();
  });

  it("shows the backend's error for an unknown user and rejects invalid names without fetching", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse(404, {
        error: "not_found",
        message: "No Sleeper user named 'ghost'.",
      }),
    );
    const user = userEvent.setup();
    render(<ManagersPage />);
    await search(user, "ghost");
    expect(
      await screen.findByText("No Sleeper user named 'ghost'."),
    ).toBeTruthy();

    global.fetch.mockClear();
    await user.clear(screen.getByLabelText("Sleeper username"));
    await search(user, "bad name!");
    await waitFor(() =>
      expect(screen.getByText(/letters, numbers and underscores/)).toBeTruthy(),
    );
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("auto-runs a deep-linked ?username=", async () => {
    window.history.replaceState(null, "", "/managers?username=dynastyfan");
    global.fetch = vi.fn(async () => jsonResponse(200, PROFILE));
    render(<ManagersPage />);
    await screen.findByRole("heading", { name: "Dynasty Fan" });
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});

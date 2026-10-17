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

function routedFetch(activity = ACTIVITY, activityStatus = 200) {
  return vi.fn(async (url) =>
    String(url).includes("/activity")
      ? jsonResponse(activityStatus, activity)
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

const activityCalls = () =>
  global.fetch.mock.calls.filter(([u]) => String(u).includes("/activity"));

describe("Manager Intelligence activity tabs", () => {
  it("fetches activity only when a tab is first opened, then keeps it", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    expect(screen.getByRole("tab", { name: "Portfolio" })).toBeTruthy();
    expect(activityCalls()).toHaveLength(0);

    await user.click(screen.getByRole("tab", { name: "Recent trades" }));
    await screen.findAllByText("Open in Trade Calculator");
    expect(activityCalls().map(([u]) => u)).toEqual([
      "/api/manager-intel/activity?username=dynastyfan",
    ]);

    await user.click(screen.getByRole("tab", { name: "Portfolio" }));
    await user.click(screen.getByRole("tab", { name: "Acquisitions" }));
    expect(activityCalls()).toHaveLength(1);
  });

  it("renders trade sides, model, unavailable at-time and the coverage banner", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Recent trades" }));
    const [link] = await screen.findAllByText("Open in Trade Calculator");
    expect(link.getAttribute("href")).toMatch(/^\/trade\?share=/);

    const [first, second] = screen.getAllByRole("article");
    expect(within(first).getByText(/\+4,200 adjusted/)).toBeTruthy();
    expect(within(first).getByText(/KTC Value Adjustment/)).toBeTruthy();
    expect(
      within(first).getAllByText(/Unavailable — no recorded value before/)
        .length,
    ).toBeGreaterThan(0);
    expect(within(first).getByText(/without FAAB/)).toBeTruthy();
    // An unpriced asset is "—" and the totals say why, never 0.
    expect(within(second).getAllByText("—").length).toBeGreaterThan(0);
    expect(
      within(second).getByText(/Totals withheld: Zed Unranked/),
    ).toBeTruthy();
    expect(
      within(second).getByText(/an asset has no current value/),
    ).toBeTruthy();

    expect(screen.getByText("Some leagues were not fully read")).toBeTruthy();
    expect(
      screen.getByText(/Beta League: transactions partly read/),
    ).toBeTruthy();
  });

  it("acquisitions show method detail, undated draft picks and analytics", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Acquisitions" }));
    await screen.findByText("Waiver · $12");
    expect(screen.getByText("Draft · 2.06")).toBeTruthy();
    expect(screen.getByText("Undated (on or before May 1, 2026)")).toBeTruthy();
    expect(screen.getByText("Acquisition analytics")).toBeTruthy();
    expect(screen.getByText(/1 move made by someone other/)).toBeTruthy();
  });

  it("the feed flags a possible previous owner's move", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Activity" }));
    await screen.findByText("Waiver claim");
    expect(
      screen.getByText(/Possibly the roster's previous owner/),
    ).toBeTruthy();
    expect(screen.getByText(/\$3 FAAB/)).toBeTruthy();
  });

  it("changing the window refetches with that window", async () => {
    global.fetch = routedFetch();
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Recent trades" }));
    await screen.findAllByText("Open in Trade Calculator");
    await user.click(screen.getByRole("radio", { name: "90 days" }));
    await vi.waitFor(() => expect(activityCalls()).toHaveLength(2));
    expect(activityCalls()[1][0]).toBe(
      "/api/manager-intel/activity?username=dynastyfan&window=90d",
    );
  });

  it("a rate-limited activity lookup says so", async () => {
    global.fetch = routedFetch({ error: "rate_limited" }, 429);
    const user = userEvent.setup();
    render(<ManagersPage />);
    await lookUp(user);
    await user.click(screen.getByRole("tab", { name: "Recent trades" }));
    await screen.findByText("Activity unavailable");
    expect(screen.getByText(/Too many lookups/)).toBeTruthy();
  });
});

/**
 * Custom alerts on /settings (2026-11-16 verified sweep, defects 2 and 6).
 *
 * Before: a failed load rendered "No alerts configured yet" and Save then
 * PUT that empty list over the alerts the server still held; Remove took
 * the rule off the screen before the server answered, so a failed delete
 * looked like a delete; and no rule control had a programmatic name.
 *
 * Review follow-up (PR #2224): an emptied number stays empty (never 0) and
 * blocks Save; rule inputs are locked while a save/remove is in flight; the
 * Remove button's name follows its visible "Removing…" text.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import CustomAlertsConfigurator from "@/components/CustomAlertsConfigurator";

const RULE_A = {
  id: "alert_a",
  kind: "value_crosses",
  displayName: "Josh Allen",
  params: { threshold: 8000, direction: "below" },
  channels: ["email"],
};
const RULE_B = {
  id: "alert_b",
  kind: "rank_change",
  displayName: "Bijan Robinson",
  params: { minDelta: 12 },
  channels: ["email", "push"],
};

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

/** fetch double: GET answers from `gets` in order; PUT from `puts`. */
function installFetch({ gets = [], puts = [] }) {
  const calls = [];
  globalThis.fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || "GET").toUpperCase();
    calls.push({ url: String(url), method, body: init.body ? JSON.parse(init.body) : null });
    const queue = method === "PUT" ? puts : gets;
    const next = queue.shift();
    if (!next) throw new Error(`unexpected ${method} ${url}`);
    return typeof next === "function" ? next() : next;
  });
  return calls;
}

function putCalls(calls) {
  return calls.filter((c) => c.method === "PUT");
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("load failure is its own state", () => {
  it("a failed load never claims there are no alerts, and offers no Save", async () => {
    const calls = installFetch({ gets: [jsonResponse(500, { error: "boom" })] });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    const failed = await screen.findByTestId("custom-alerts-load-failed");
    expect(failed.textContent).toMatch(/your custom alerts/);
    expect(failed.textContent).toMatch(/Nothing has been changed/);
    expect(screen.queryByText(/No alerts configured yet/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Save all/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Value alert/ })).toBeNull();
    expect(putCalls(calls)).toEqual([]);
  });

  it("a network error is a failure too", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    expect((await screen.findByTestId("custom-alerts-load-failed")).textContent).toMatch(
      /Could not reach the server/,
    );
    expect(screen.queryByText(/No alerts configured yet/)).toBeNull();
  });

  it("a 200 without a rules list is not an empty list", async () => {
    installFetch({ gets: [jsonResponse(200, { unexpected: true })] });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    expect(await screen.findByTestId("custom-alerts-load-failed")).toBeTruthy();
    expect(screen.queryByText(/No alerts configured yet/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Save all/ })).toBeNull();
  });

  it("Try again reloads, and the saved alerts appear once it succeeds", async () => {
    const calls = installFetch({
      gets: [jsonResponse(503, { error: "data_not_ready" }), jsonResponse(200, { rules: [RULE_A] })],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByTestId("custom-alerts-load-failed");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByDisplayValue("Josh Allen")).toBeTruthy();
    expect(screen.queryByTestId("custom-alerts-load-failed")).toBeNull();
    expect(screen.getByRole("button", { name: "Save all" })).toBeEnabled();
    expect(calls.filter((c) => c.method === "GET")).toHaveLength(2);
  });

  it("an empty saved list (a successful load) does say there are no alerts", async () => {
    installFetch({ gets: [jsonResponse(200, { rules: [] })] });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    expect(await screen.findByText(/No alerts configured yet/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save all" })).toBeEnabled();
  });
});

describe("Remove changes the list only after the server confirms", () => {
  it("a failed delete keeps the alert and says it is still saved", async () => {
    const calls = installFetch({
      gets: [jsonResponse(200, { rules: [RULE_A, RULE_B] })],
      puts: [jsonResponse(500, { error: "write_failed" })],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    fireEvent.click(screen.getByRole("button", { name: "Remove the Josh Allen alert" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Couldn't remove the alert.*It is still saved/);
    expect(screen.getByDisplayValue("Josh Allen")).toBeTruthy();
    expect(putCalls(calls)).toHaveLength(1);
    expect(putCalls(calls)[0].body.rules.map((r) => r.id)).toEqual(["alert_b"]);
  });

  it("the alert stays on screen while the delete is in flight, then goes", async () => {
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    installFetch({
      gets: [jsonResponse(200, { rules: [RULE_A, RULE_B] })],
      puts: [() => pending],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    fireEvent.click(screen.getByRole("button", { name: "Remove the Josh Allen alert" }));
    // Not yet confirmed: still listed, and nothing else can be saved meanwhile.
    expect(screen.getByDisplayValue("Josh Allen")).toBeTruthy();
    // The name follows the visible text (label in name), and says it is busy.
    const removing = screen.getByRole("button", { name: "Removing the Josh Allen alert" });
    expect(removing.textContent).toBe("Removing…");
    expect(removing.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("button", { name: "Save all" })).toBeDisabled();
    // No rule can be edited while the server is answering.
    expect(screen.getByRole("combobox", { name: "Player name for alert 2" })).toBeDisabled();
    await act(async () => {
      release(jsonResponse(200, { rules: [RULE_B] }));
    });
    await waitFor(() => expect(screen.queryByDisplayValue("Josh Allen")).toBeNull());
    expect(screen.getByDisplayValue("Bijan Robinson")).toBeTruthy();
  });

  it("removing one alert never saves another alert's unsaved edits", async () => {
    const calls = installFetch({
      gets: [jsonResponse(200, { rules: [RULE_A, RULE_B] })],
      puts: [jsonResponse(200, { rules: [RULE_B] })],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    fireEvent.change(screen.getByRole("combobox", { name: "Player name for alert 2" }), {
      target: { value: "Bijan (typo, unsaved)" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove the Josh Allen alert" }));
    await waitFor(() => expect(screen.queryByDisplayValue("Josh Allen")).toBeNull());
    expect(putCalls(calls)[0].body.rules).toEqual([RULE_B]);
    // The unsaved draft is still on screen for the user to save or discard.
    expect(screen.getByDisplayValue("Bijan (typo, unsaved)")).toBeTruthy();
  });

  it("removing a never-saved alert is local and sends nothing", async () => {
    const calls = installFetch({ gets: [jsonResponse(200, { rules: [] })] });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByText(/No alerts configured yet/);
    fireEvent.click(screen.getByRole("button", { name: "+ Value alert" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove alert 1" }));
    expect(screen.getByText(/No alerts configured yet/)).toBeTruthy();
    expect(putCalls(calls)).toEqual([]);
  });
});

describe("Save", () => {
  it("shows the list the server confirmed, not the one it was sent", async () => {
    // The server's answer differs from what was sent (it rounds and
    // normalises), so the screen can only match it by reading the response.
    const confirmed = { ...RULE_A, params: { threshold: 8100, direction: "below" } };
    const calls = installFetch({
      gets: [jsonResponse(200, { rules: [RULE_A] })],
      puts: [jsonResponse(200, { rules: [confirmed] })],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    fireEvent.click(screen.getByRole("button", { name: "Save all" }));
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(putCalls(calls)[0].body.rules).toEqual([RULE_A]);
    expect(
      screen.getByRole("spinbutton", { name: "Threshold (canonical value) for the Josh Allen alert" })
        .value,
    ).toBe("8100");
  });

  it("locks every rule input while the save is in flight", async () => {
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    installFetch({
      gets: [jsonResponse(200, { rules: [RULE_A] })],
      puts: [() => pending],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    fireEvent.click(screen.getByRole("button", { name: "Save all" }));
    const card = screen.getByTestId("custom-alert-alert_a");
    for (const el of card.querySelectorAll("input, select")) {
      expect(el, el.outerHTML.slice(0, 120)).toBeDisabled();
    }
    await act(async () => {
      release(jsonResponse(200, { rules: [RULE_A] }));
    });
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Player name for alert 1" })).toBeEnabled(),
    );
  });

  it("an emptied threshold stays empty, is never saved as 0, and Save says why", async () => {
    const calls = installFetch({ gets: [jsonResponse(200, { rules: [RULE_A] })] });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    const threshold = screen.getByRole("spinbutton", {
      name: "Threshold (canonical value) for the Josh Allen alert",
    });
    fireEvent.change(threshold, { target: { value: "" } });
    expect(threshold.value).toBe("");
    expect(threshold.getAttribute("aria-invalid")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Save all" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /Enter a threshold for the Josh Allen alert before saving\. Nothing was saved\./,
    );
    expect(putCalls(calls)).toEqual([]);
  });

  it("an emptied position count stays empty and blocks Save too", async () => {
    const calls = installFetch({ gets: [jsonResponse(200, { rules: [RULE_B] })] });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Bijan Robinson");
    const delta = screen.getByRole("spinbutton", {
      name: "At least how many positions for the Bijan Robinson alert",
    });
    fireEvent.change(delta, { target: { value: "" } });
    expect(delta.value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Save all" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /Enter how many positions for the Bijan Robinson alert/,
    );
    expect(putCalls(calls)).toEqual([]);
  });

  it("a failed save keeps the drafts and reports the server's reason", async () => {
    installFetch({
      gets: [jsonResponse(200, { rules: [RULE_A] })],
      puts: [jsonResponse(400, { error: "invalid_rule", detail: "threshold out of range" })],
    });
    render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    fireEvent.click(screen.getByRole("button", { name: "Save all" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/threshold out of range/);
    expect(screen.getByDisplayValue("Josh Allen")).toBeTruthy();
  });
});

describe("every rule control has a programmatic name", () => {
  it("selects, inputs and Remove name what they edit", async () => {
    installFetch({ gets: [jsonResponse(200, { rules: [RULE_A, RULE_B] })] });
    const { container } = render(<CustomAlertsConfigurator enabled players={[]} />);
    await screen.findByDisplayValue("Josh Allen");
    const a = screen.getByTestId("custom-alert-alert_a");
    expect(within(a).getByRole("combobox", { name: "Alert type for the Josh Allen alert" })).toBeTruthy();
    expect(within(a).getByRole("combobox", { name: "Direction for the Josh Allen alert" })).toBeTruthy();
    expect(
      within(a).getByRole("spinbutton", { name: "Threshold (canonical value) for the Josh Allen alert" }),
    ).toBeTruthy();
    expect(within(a).getByRole("combobox", { name: "Player name for alert 1" })).toBeTruthy();
    const b = screen.getByTestId("custom-alert-alert_b");
    expect(
      within(b).getByRole("spinbutton", { name: "At least how many positions for the Bijan Robinson alert" }),
    ).toBeTruthy();
    expect(within(b).getByRole("checkbox", { name: "Push" })).toBeChecked();
    for (const el of container.querySelectorAll("input, select")) {
      const named = el.getAttribute("aria-label") || el.closest("label");
      expect(named, el.outerHTML.slice(0, 120)).toBeTruthy();
    }
  });
});

describe("signed out", () => {
  it("asks to sign in and makes no request", () => {
    const calls = installFetch({});
    render(<CustomAlertsConfigurator enabled={false} players={[]} />);
    expect(screen.getByText(/Sign in to set up custom alerts/)).toBeTruthy();
    expect(calls).toEqual([]);
  });
});

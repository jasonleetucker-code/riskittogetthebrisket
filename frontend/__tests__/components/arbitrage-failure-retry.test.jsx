// /arbitrage Package Builder and Trade Desk — a failed request renders the
// shared TradeToolErrorBanner (a sentence, the code only as a detail) with a
// "Try again" that re-issues exactly the failed request (X-FRONTEND-FAILURE-SW).
// Both used to print the raw error text with no retry.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import PackageBuilderView from "@/app/arbitrage/PackageBuilderView";
import TradeDeskView, { deskFailure } from "@/app/arbitrage/TradeDeskView";

const TEAMS = [
  { name: "Us", players: ["Our WR", "Our RB"] },
  { name: "Them", players: ["Their QB", "Their WR"] },
];

let originalFetch;
beforeEach(() => {
  originalFetch = global.fetch;
  window.localStorage.clear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("Package Builder failure", () => {
  it("a 503 says the builder is not ready, and Try again re-sends the request", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ error: "data_not_ready" }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ packages: [] }) });
    render(<PackageBuilderView myTeam="Us" leagueKey="lg" ownerKey="me" teams={TEAMS} />);
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    expect(await screen.findByText(/rosters and values are not loaded/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(global.fetch.mock.calls[1][0]).toBe("/api/trade/package-builder");
    expect(global.fetch.mock.calls[1][1].body).toBe(global.fetch.mock.calls[0][1].body);
    await waitFor(() => expect(screen.queryByText(/rosters and values are not loaded/)).toBeNull());
  });

  it("a dropped connection reads as unreachable, never as the raw TypeError", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    render(<PackageBuilderView myTeam="Us" leagueKey="lg" ownerKey="me" teams={TEAMS} />);
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    expect(await screen.findByText(/Package Builder could not reach the server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Trade Desk failure", () => {
  it("a failed load offers Try again, which re-loads the desk", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ leagueKey: "main", count: 0, limit: 100, items: [] }),
      });
    render(<TradeDeskView leagueKey="main" />);
    expect(
      await screen.findByText("Could not reach the server; nothing was changed."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(global.fetch.mock.calls[1][0]).toBe("/api/user/trade-desk?leagueKey=main");
    expect(await screen.findByText("Your Trade Desk is empty")).toBeInTheDocument();
  });

  it("a signed-out refusal offers no retry", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "auth_required" }),
    });
    render(<TradeDeskView leagueKey="main" />);
    expect(await screen.findByText("Sign in to use the Trade Desk.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("deskFailure keeps the desk's sentence and never shows a client placeholder as a code", () => {
    expect(deskFailure({ ok: false, code: "network", status: 0 })).toEqual({
      message: "Could not reach the server; nothing was changed.",
      code: "",
      detail: "",
      retryable: true,
    });
    expect(deskFailure({ ok: false, code: "not_found", status: 404 }).retryable).toBe(false);
    expect(deskFailure({ ok: false, code: "error", status: 500 })).toMatchObject({
      code: "",
      retryable: true,
    });
  });
});

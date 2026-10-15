import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import TradeDeskView from "@/app/arbitrage/TradeDeskView";

const ITEM = {
  id: "0123456789abcdef",
  myTeam: "Us",
  opponent: "Them",
  send: [{ name: "Our WR", isPick: false }],
  receive: [{ name: "Their RB", isPick: false }],
  source: "best_offers",
  status: "candidate",
  statusHistory: [
    { status: "candidate", at: "2026-10-15T12:00:00+00:00", setBy: "user" },
  ],
  note: "",
  rosterCheck: {
    state: "changed",
    noLongerInPlace: ["Their RB"],
    picksNotChecked: 0,
  },
};

function desk(items) {
  return { leagueKey: "main", count: items.length, limit: 100, items };
}

function ok(body) {
  return { ok: true, status: 200, json: async () => body };
}

describe("Trade Desk view", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("lists saved packages with the roster evidence and no send action", async () => {
    global.fetch = vi.fn().mockResolvedValue(ok(desk([ITEM])));
    render(<TradeDeskView leagueKey="main" />);
    expect(await screen.findByText("Us → Them")).toBeInTheDocument();
    expect(
      screen.getByText("Roster changed: Their RB no longer in place"),
    ).toBeInTheDocument();
    expect(screen.getByText(/You marked Candidate on/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open in Trade Calculator" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
    expect(global.fetch.mock.calls[0][0]).toBe(
      "/api/user/trade-desk?leagueKey=main",
    );
  });

  it("a status change is a PATCH the user made", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(ok(desk([ITEM])))
      .mockResolvedValueOnce(ok(desk([{ ...ITEM, status: "manually_sent" }])));
    render(<TradeDeskView leagueKey="main" />);
    await screen.findByText("Us → Them");
    await user.selectOptions(screen.getByLabelText("Status"), "manually_sent");
    const [url, init] = global.fetch.mock.calls[1];
    expect(url).toBe("/api/user/trade-desk/0123456789abcdef");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({
      leagueKey: "main",
      status: "manually_sent",
    });
  });

  it("an empty desk says how to add to it", async () => {
    global.fetch = vi.fn().mockResolvedValue(ok(desk([])));
    render(<TradeDeskView leagueKey="main" />);
    expect(
      await screen.findByText("Your Trade Desk is empty"),
    ).toBeInTheDocument();
  });

  it("a signed-out user sees why, not an empty desk", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ error: "auth_required" }),
      });
    render(<TradeDeskView leagueKey="main" />);
    expect(
      await screen.findByText("Sign in to use the Trade Desk."),
    ).toBeInTheDocument();
  });
});

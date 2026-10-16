import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SaveToDeskButton from "@/components/trade/SaveToDeskButton";

const body = (receive) => ({
  leagueKey: "main",
  myTeam: "Us",
  opponent: "Them",
  source: "best_offers",
  send: [{ name: "Our WR", isPick: false }],
  receive: [{ name: receive, isPick: false }],
});

describe("Save to Trade Desk", () => {
  const original = global.fetch;
  afterEach(() => {
    global.fetch = original;
  });

  it("'Saved' belongs to the package, not to the card slot", async () => {
    const user = userEvent.setup();
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
    const { rerender } = render(<SaveToDeskButton body={body("Their RB")} />);
    await user.click(
      screen.getByRole("button", { name: "Save to Trade Desk" }),
    );
    expect(
      await screen.findByText("Saved to your Trade Desk"),
    ).toBeInTheDocument();
    rerender(<SaveToDeskButton body={body("Their QB")} />);
    expect(
      await screen.findByRole("button", { name: "Save to Trade Desk" }),
    ).toBeInTheDocument();
  });

  it("a network failure ends the save instead of hanging on 'Saving…'", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    render(<SaveToDeskButton body={body("Their RB")} />);
    await user.click(
      screen.getByRole("button", { name: "Save to Trade Desk" }),
    );
    expect(
      await screen.findByText(/Could not reach the server/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save to Trade Desk" }),
    ).toBeEnabled();
  });
});

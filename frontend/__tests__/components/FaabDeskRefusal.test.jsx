/**
 * CW-50 — the bid desk renders "no honest bid for this claim" as that,
 * not as the desk being down.
 *
 * ``POST /api/waiver/faab-recommend`` refuses three cases with a named error
 * and a sentence: an add or a drop the board does not price (422
 * ``add_player_unpriced`` / ``drop_player_unpriced`` — a figure would be
 * fabricated, and an unpriced drop is never free) and a player already on a
 * roster in this league (409 ``add_player_not_available`` — not a waiver
 * claim).  The panel used to print the raw status line under
 * "FAAB recommender unavailable".  Any other failure keeps that treatment.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

import FaabRecommendation, { deskRefusal } from "@/components/waivers/FaabRecommendation";

function mockFailure(status, body) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: false, status, text: async () => text }),
  );
}

function renderDesk() {
  return render(
    <FaabRecommendation
      addPlayer={{ name: "Rival Wr" }}
      dropPlayer={null}
      leagueKey="dynasty_main"
      ownerId="me"
      selectedTeam={{ ownerId: "me", name: "Me" }}
      leagueFaab={null}
    />,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("deskRefusal", () => {
  it("names a rostered player as a no-bid, with the backend's sentence", () => {
    expect(
      deskRefusal(409, JSON.stringify({ error: "add_player_not_available", message: "on Rival One" })),
    ).toEqual({ kind: "noBid", message: "on Rival One" });
  });

  it("names an unpriced add or drop as a no-bid", () => {
    expect(deskRefusal(422, JSON.stringify({ error: "add_player_unpriced", message: "unpriced" })))
      .toEqual({ kind: "noBid", message: "unpriced" });
    expect(deskRefusal(422, JSON.stringify({ error: "drop_player_unpriced", message: "drop" })))
      .toEqual({ kind: "noBid", message: "drop" });
  });

  it("keeps every other failure as the desk being unavailable", () => {
    expect(deskRefusal(503, JSON.stringify({ error: "faab_config_invalid", message: "bad" })).kind)
      .toBe("unavailable");
    expect(deskRefusal(500, "<html>oops</html>")).toEqual({
      kind: "unavailable",
      message: "API 500: <html>oops</html>",
    });
  });
});

describe("FAAB desk refusal rendering", () => {
  it("shows a rostered player as 'No bid for this claim' with the reason", async () => {
    mockFailure(409, {
      error: "add_player_not_available",
      message: "Rival Wr is already on Rival One in this league — not a waiver claim.",
    });
    renderDesk();
    await waitFor(() => expect(screen.getByText("No bid for this claim")).toBeTruthy());
    expect(screen.getByText(/already on Rival One/)).toBeTruthy();
    expect(screen.queryByText("FAAB recommender unavailable")).toBeNull();
  });

  it("keeps a server failure as 'FAAB recommender unavailable'", async () => {
    mockFailure(500, { error: "failed" });
    renderDesk();
    await waitFor(() => expect(screen.getByText("FAAB recommender unavailable")).toBeTruthy());
  });
});

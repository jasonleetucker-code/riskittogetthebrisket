// Package Builder Sending / Receiving (owner directive 2026-10-18, Batch 2):
// independent sides, default Both, sent to the server which applies them
// during candidate generation; conflicts the server reports are shown.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/trade-share", () => ({ buildShareUrl: () => "/trade?share=x" }));

import PackageBuilderView from "@/app/arbitrage/PackageBuilderView";
import { BUILDER_MODES, buildRequest } from "@/lib/package-builder";

const TEAMS = [
  { name: "Us", players: ["Our WR", "Our LB"] },
  { name: "Them", players: ["Their QB", "Their LB"] },
];
const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const body = (call) => JSON.parse(call[1].body);
const SCOPES = ["both", "offense", "defense"];

describe("Package Builder Sending / Receiving", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("defaults to Both / Both and omits them, keeping the legacy request byte-identical", () => {
    const req = buildRequest({ myTeam: "Us", maxSide: 2 });
    expect(req.sending).toBeUndefined();
    expect(req.receiving).toBeUndefined();
    expect(req.discovery).toBeUndefined();
  });

  it("builds a request for all nine combinations", () => {
    for (const s of SCOPES) {
      for (const r of SCOPES) {
        const req = buildRequest({ myTeam: "Us", maxSide: 3, sending: s, receiving: r });
        expect(req.sending).toBe(s === "both" ? undefined : s);
        expect(req.receiving).toBe(r === "both" ? undefined : r);
      }
    }
  });

  it.each(BUILDER_MODES.map((m) => m.value))(
    "sends Sending / Receiving and the shared discovery in %s mode",
    async (mode) => {
      const user = userEvent.setup();
      global.fetch = vi.fn().mockResolvedValue(ok({ packages: [] }));
      render(
        <PackageBuilderView
          myTeam="Us"
          leagueKey="lg"
          ownerKey="me"
          teams={TEAMS}
          discovery={{ targetQuality: "top100", playersToTarget: "both", sort: "most_impactful", minIncomingValue: "" }}
        />,
      );
      await user.click(screen.getByRole("radio", { name: BUILDER_MODES.find((m) => m.value === mode).label }));
      if (mode === "acquire") await user.type(screen.getByLabelText("Player or pick you want"), "Their QB");
      if (mode === "sell") await user.selectOptions(screen.getByLabelText("Player to sell"), "Our LB");
      if (mode === "improve") await user.selectOptions(screen.getByLabelText("Position to improve"), "QB");
      await user.selectOptions(screen.getByLabelText("Sending"), "defense");
      await user.selectOptions(screen.getByLabelText("Receiving"), "offense");
      await user.click(screen.getByRole("button", { name: "Build packages" }));
      await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
      const sent = body(global.fetch.mock.calls[0]);
      expect(sent.sending).toBe("defense");
      expect(sent.receiving).toBe("offense");
      expect(sent.discovery.targetQuality).toBe("top100");
    },
  );

  it("shows the conflicts the server reports instead of hiding them", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(
      ok({
        packages: [],
        noResultReason: "target_outside_receiving",
        noResultLabel: "No package found",
        noResultDetail: "Their LB (LB) is outside Receiving (Offense). Widen Receiving to build for him.",
        sides: { selectedOutgoingOutsideSending: ["Our WR"], returnPositionsOutsideReceiving: ["LB"] },
      }),
    );
    render(<PackageBuilderView myTeam="Us" leagueKey="lg" ownerKey="me" teams={TEAMS} />);
    await user.click(screen.getByRole("button", { name: "Build packages" }));
    expect(await screen.findByText(/outside Receiving \(Offense\)/)).toBeInTheDocument();
    expect(screen.getByText(/Not offered \(outside Sending\): Our WR/)).toBeInTheDocument();
    expect(screen.getByText(/Ignored \(outside Receiving\): LB/)).toBeInTheDocument();
  });
});

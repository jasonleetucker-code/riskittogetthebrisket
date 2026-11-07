// LI1842-DEFECT-03 review nit -- the home Terminal "Top movers" panel must
// name the ACTIVE league on its /api/movers request (the server now applies the
// board's scoring-identity gate to that route), and a 503 data_not_ready must
// render as an explained "unavailable" state, never the raw "HTTP 503".
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const appState = { rawData: null, openPlayerPopup: vi.fn() };
const leagueState = { selectedLeagueKey: "dynasty_new", loading: false };

vi.mock("@/components/AppShell", () => ({ useApp: () => appState }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => leagueState }));

import MoversPanel from "@/components/terminal/MoversPanel";

const MOVER = {
  name: "Rising Rb",
  team: "BUF",
  position: "RB",
  playerId: "4046",
  rankNow: 12,
  rankThen: 32,
  delta: 20,
  assetClass: "offense",
  valueNow: 7421,
  currentSourceRanks: { ktc: 10 },
};

function okResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

function failResponse(status, body) {
  return {
    ok: false,
    status,
    json: async () => {
      if (body === undefined) throw new SyntaxError("no json");
      return body;
    },
  };
}

function moversCalls() {
  return fetch.mock.calls.filter(([url]) => String(url).startsWith("/api/movers"));
}

beforeEach(() => {
  leagueState.selectedLeagueKey = "dynasty_new";
  leagueState.loading = false;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(okResponse({ risers: [MOVER], fallers: [] })),
  );
});

describe("MoversPanel -- league scope", () => {
  it("sends the active league key on the movers request", async () => {
    render(<MoversPanel />);
    await waitFor(() => expect(moversCalls()).toHaveLength(1));
    const url = new URL(moversCalls()[0][0], "http://x");
    expect(url.searchParams.get("leagueKey")).toBe("dynasty_new");
    expect(url.searchParams.get("window")).toBe("14");
    expect(url.searchParams.get("threshold")).toBe("15");
    expect(url.searchParams.get("limit")).toBe("8");
    await waitFor(() => expect(screen.getByText("Rising Rb")).toBeTruthy());
  });

  it("does not request anything until the league registry has resolved", async () => {
    leagueState.loading = true;
    leagueState.selectedLeagueKey = "";
    render(<MoversPanel />);
    // Give any (wrongly) eager effect a chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(moversCalls()).toHaveLength(0);
  });

  it("omits the key (rather than sending an empty one) when no league resolves", async () => {
    leagueState.selectedLeagueKey = "";
    render(<MoversPanel />);
    await waitFor(() => expect(moversCalls()).toHaveLength(1));
    const url = new URL(moversCalls()[0][0], "http://x");
    expect(url.searchParams.has("leagueKey")).toBe(false);
  });
});

describe("MoversPanel -- 503 data_not_ready", () => {
  it("renders an explained unavailable state, not the raw status", async () => {
    fetch.mockResolvedValue(
      failResponse(503, {
        error: "data_not_ready",
        message:
          "Rankings are not compatible: league 'dynasty_new' scores players differently from the scoring the loaded rankings were built under.",
        leagueKey: "dynasty_new",
      }),
    );
    const { container } = render(<MoversPanel />);
    await waitFor(() =>
      expect(screen.getByText(/Movers are unavailable for this league/)).toBeTruthy(),
    );
    // The server's reason is shown, the raw status is not, and no empty
    // "No qualifying movers" columns claim the market is quiet.
    expect(container.textContent).toContain("scores players differently");
    expect(container.textContent).not.toContain("HTTP 503");
    expect(container.textContent).not.toContain("No qualifying movers");
    expect(container.textContent).not.toContain("Risers");
  });

  it("still gives a readable reason when the 503 body states none", async () => {
    fetch.mockResolvedValue(failResponse(503, { error: "data_not_ready" }));
    const { container } = render(<MoversPanel />);
    await waitFor(() =>
      expect(screen.getByText(/Movers are unavailable for this league/)).toBeTruthy(),
    );
    expect(container.textContent).toContain("rankings board is not loaded");
    expect(container.textContent).not.toContain("HTTP 503");
  });

  it("a non-JSON 503 (proxy page) is a plain error, not the explained league state", async () => {
    fetch.mockResolvedValue(failResponse(503, undefined));
    const { container } = render(<MoversPanel />);
    await waitFor(() => expect(container.textContent).toContain("briefly unavailable"));
    expect(container.textContent).not.toContain("Movers are unavailable for this league");
  });
});

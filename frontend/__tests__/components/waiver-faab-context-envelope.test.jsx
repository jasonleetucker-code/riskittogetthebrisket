// The /waivers league-FAAB context strip unwrapped the wrong key.
//
// Audit finding W11-F006. `ManualAddDrop` fetches the lazy public-league
// section `/api/public/league/faabAnalytics`, whose envelope is built by
// `src/public_league/public_contract.py::build_section_payload` as
// `{contractVersion, league, section, data}` — the body sits under
// **data**. The component unwrapped `data?.body || data`, and since
// `body` has never existed on that envelope, the `||` fell through to
// the envelope ITSELF. Every field the strip reads
// (`leagueBudget`, `leagueAvgWinningBid`, `leagueMedianWinningBid`)
// therefore resolved to undefined and the tiles rendered "—" against a
// response that carried the real numbers.
//
// The failure is invisible in isolation: an em-dash reads as "this
// league has no FAAB history", which is exactly what a genuinely empty
// analytics block also renders. So the test pins BOTH — the populated
// envelope must produce numbers, and a genuinely empty body must still
// produce the em-dash — otherwise a fix that hard-codes a fallback
// would pass.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import ManualAddDrop from "@/components/waivers/ManualAddDrop";

/** The real backend envelope for a lazy public-league section. */
function sectionEnvelope(body) {
  return {
    contractVersion: "2026-03-10.v2",
    league: { name: "Risk It To Get The Brisket", teamCount: 12 },
    section: "faabAnalytics",
    data: body,
  };
}

const POPULATED = {
  leagueBudget: 100,
  leagueAvgWinningBid: 17.4,
  leagueMedianWinningBid: 12,
  seasons: [],
};

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const TEAM = {
  name: "Mine",
  players: [],
  faabRemaining: 63,
  // faabBudget deliberately absent: the strip's `budget` falls back to
  // the league analytics value, which is the envelope-dependent read.
};

const ROWS = [
  {
    name: "Emeka Egbuka",
    pos: "WR",
    rankDerivedValue: 3100,
    assetClass: "offense",
    values: { full: 3100 },
  },
];

function renderPanel() {
  return render(
    <ManualAddDrop
      rows={ROWS}
      selectedTeam={TEAM}
      sleeperTeams={[]}
      leagueKey="dynasty_main"
      settings={{}}
    />,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("league FAAB context strip — response envelope", () => {
  it("reads the section body from `data`, the key the backend actually sends", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(sectionEnvelope(POPULATED))));

    renderPanel();

    // The average tile: 17.4 -> "$17". Before the fix this stayed "—"
    // because `envelope.leagueAvgWinningBid` is undefined.
    await waitFor(() =>
      expect(screen.getByText("League average bid").closest("*")).toBeTruthy(),
    );
    await waitFor(() => expect(screen.getByText("$17")).toBeInTheDocument());
    expect(screen.getByText("$12")).toBeInTheDocument();
    // `budget` falls back to the league value when the team carries none.
    expect(screen.getByText("of $100")).toBeInTheDocument();
  });

  it("still shows an em-dash when the league genuinely has no bid history", async () => {
    // Guards against a "fix" that invents numbers: zero is the real
    // observed value here, and zero must not render as a dollar figure.
    vi.stubGlobal("fetch", vi.fn(async () =>
      jsonResponse(
        sectionEnvelope({
          leagueBudget: 100,
          leagueAvgWinningBid: 0,
          leagueMedianWinningBid: 0,
          seasons: [],
        }),
      ),
    ));

    renderPanel();

    await waitFor(() => expect(screen.getByText("of $100")).toBeInTheDocument());
    expect(screen.queryByText("$17")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("requests the faabAnalytics section for the active league", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(sectionEnvelope(POPULATED)));
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/public/league/faabAnalytics");
    expect(url).toContain("leagueKey=dynasty_main");
  });

  it("stays silent when the section 404s — the strip is optional context", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "nope" }, 404)));

    renderPanel();

    // Your-FAAB still renders from the team; no league numbers appear.
    await waitFor(() => expect(screen.getByText("$63")).toBeInTheDocument());
    expect(screen.queryByText("$17")).not.toBeInTheDocument();
  });
});

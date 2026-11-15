// V1-56 / issue #1151 — the /waivers league-FAAB context strip must render
// when NO fantasy team is selected.
//
// Production verification (run 32919648642) saw the page's own
// `GET /api/public/league/faabAnalytics` return populated analytics
// (mean winning bid 1.37 over 1102 bids) while the "League average bid"
// tile did not exist, because `FaabHeaderStat` lived only inside the
// calculator's selected-team branch.  An ephemeral guest has no persisted
// team, so a populated, measured league-level answer was hidden entirely.
//
// The strip is two independent halves:
//   - league tiles   -> a property of the LEAGUE; render whenever the
//                       canonical `faabAnalytics` section answered;
//   - "Your FAAB"    -> a property of a TEAM; with none selected it is
//                       UNKNOWN ("—"), never $0.
//
// MISSING IS NEVER ZERO in both directions, which is why the cases below
// pair every "renders a number" assertion with an "unavailable renders a
// reason, not a zero" one: a fix that merely hard-coded `$0` / hid the strip
// would pass half of them.  No FAAB math is under test -- the frontend only
// formats what the backend served.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import ManualAddDrop from "@/components/waivers/ManualAddDrop";

function sectionEnvelope(body) {
  return {
    contractVersion: "2026-03-10.v2",
    league: { name: "Risk It To Get The Brisket", teamCount: 12 },
    section: "faabAnalytics",
    data: body,
  };
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

// The shape production served: mean 1.37 over 1102 bids, and a MEASURED $0
// median (this league's most common winning bid is free).
const PRODUCTION_LIKE = {
  leagueBudget: 100,
  leagueAvgWinningBid: 1.37,
  leagueMedianWinningBid: 0,
  totalBidsAnalyzed: 1102,
  seasons: [],
};

const TEAM = { name: "Mine", players: [], faabRemaining: 63 };
const ROWS = [
  {
    name: "Emeka Egbuka",
    pos: "WR",
    rankDerivedValue: 3100,
    assetClass: "offense",
    values: { full: 3100 },
  },
];

function renderPanel(props = {}) {
  return render(
    <ManualAddDrop
      rows={ROWS}
      selectedTeam={null}
      sleeperTeams={[]}
      leagueKey="dynasty_main"
      settings={{}}
      {...props}
    />,
  );
}

/** Read one StatTile by its label: the displayed value and its meta line. */
function tile(label) {
  const el = screen.getByText(label).closest(".ds-stat");
  expect(el, `no StatTile labelled ${label}`).not.toBeNull();
  return {
    value: el.querySelector(".ds-stat__value").textContent,
    meta: el.querySelector(".ds-stat__meta")?.textContent ?? null,
  };
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("league FAAB context with NO team selected — populated analytics", () => {
  it("renders the measured league figures; Your FAAB stays unknown, not $0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(sectionEnvelope(PRODUCTION_LIKE))),
    );

    renderPanel();

    // The exact defect: this tile did not exist. 1.37 -> "$1".
    await waitFor(() => expect(tile("League average bid").value).toBe("$1"));
    // A measured $0 median over 1102 bids is an observation, rendered as one.
    expect(tile("League median bid").value).toBe("$0");
    expect(tile("League average bid").meta).toBe("winning bids");

    const yours = tile("Your FAAB");
    expect(yours.value).toBe("—");
    expect(yours.meta).toBe("select a team");
    // The unknown balance must not be dressed up with the league budget
    // either ("of $100" beside an em-dash would read as a balance).
    expect(screen.queryByText("of $100")).not.toBeInTheDocument();
  });

  it("keeps the team-gated calculator controls gated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(sectionEnvelope(PRODUCTION_LIKE))),
    );

    renderPanel();

    await waitFor(() => expect(tile("League average bid").value).toBe("$1"));
    expect(
      screen.getByText("Select a team below to use the manual add/drop calculator."),
    ).toBeInTheDocument();
    // No add/drop pickers without a team.
    expect(screen.queryByLabelText("Search drop candidates")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Search add candidates")).not.toBeInTheDocument();
  });

  it("renders a zero mean and median as $0 only when bids were actually analysed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          sectionEnvelope({
            leagueBudget: 100,
            leagueAvgWinningBid: 0,
            leagueMedianWinningBid: 0,
            totalBidsAnalyzed: 412,
          }),
        ),
      ),
    );

    renderPanel();

    await waitFor(() => expect(tile("League average bid").value).toBe("$0"));
    expect(tile("League median bid").value).toBe("$0");
    expect(tile("Your FAAB").value).toBe("—");
  });
});

describe("league FAAB context with NO team selected — missing is never zero", () => {
  it("shows an em-dash and the reason when the league has no bids on record", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          sectionEnvelope({
            leagueBudget: 100,
            leagueAvgWinningBid: 0,
            leagueMedianWinningBid: 0,
            totalBidsAnalyzed: 0,
          }),
        ),
      ),
    );

    renderPanel();

    await waitFor(() =>
      expect(tile("League average bid").meta).toBe("no winning bids on record"),
    );
    expect(tile("League average bid").value).toBe("—");
    expect(tile("League median bid").value).toBe("—");
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("does not let a body with no bid evidence pass as a measured zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          sectionEnvelope({
            leagueBudget: 100,
            leagueAvgWinningBid: 0,
            leagueMedianWinningBid: 0,
            // totalBidsAnalyzed omitted: a zero with no count is ambiguous
            // and must render as unknown.
          }),
        ),
      ),
    );

    renderPanel();

    await waitFor(() =>
      expect(tile("League average bid").meta).toBe("bid count not reported"),
    );
    expect(tile("League average bid").value).toBe("—");
    expect(tile("League median bid").value).toBe("—");
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("states the section is unavailable (with the HTTP reason) on a failed read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "nope" }, 404)));

    renderPanel();

    await waitFor(() =>
      expect(tile("League average bid").meta).toBe("unavailable: HTTP 404"),
    );
    expect(tile("League median bid").meta).toBe("unavailable: HTTP 404");
    expect(tile("League average bid").value).toBe("—");
    expect(tile("League median bid").value).toBe("—");
    expect(tile("Your FAAB").value).toBe("—");
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("states the request failed when the network throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );

    renderPanel();

    await waitFor(() =>
      expect(tile("League average bid").meta).toBe("unavailable: request failed"),
    );
    expect(tile("League median bid").value).toBe("—");
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("does not treat an envelope with no `data` as an analytics body", async () => {
    // No ``|| envelope`` fallback (W11-F006): the envelope itself carries no
    // league figures, and pretending it does is what produced the original
    // silent failure.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          contractVersion: "2026-03-10.v2",
          section: "faabAnalytics",
          leagueAvgWinningBid: 99,
        }),
      ),
    );

    renderPanel();

    await waitFor(() =>
      expect(tile("League average bid").meta).toBe(
        "unavailable: response carried no analytics",
      ),
    );
    expect(tile("League average bid").value).toBe("—");
    expect(screen.queryByText("$99")).not.toBeInTheDocument();
  });

  it("is an explicit loading state — not $0 — while the read is in flight", async () => {
    let release;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((resolve) => {
            release = () => resolve(jsonResponse(sectionEnvelope(PRODUCTION_LIKE)));
          }),
      ),
    );

    renderPanel();

    expect(tile("League average bid")).toEqual({ value: "—", meta: "loading…" });
    expect(tile("League median bid")).toEqual({ value: "—", meta: "loading…" });
    expect(screen.queryByText("$0")).not.toBeInTheDocument();

    release();
    await waitFor(() => expect(tile("League average bid").value).toBe("$1"));
  });

  it("waits visibly (no fetch, no zero) until a league key exists", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderPanel({ leagueKey: undefined });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(tile("League average bid")).toEqual({ value: "—", meta: "waiting for league" });
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });
});

describe("league FAAB context — team selection and league switches", () => {
  it("keeps the same league figures, without refetching, once a team is chosen", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(sectionEnvelope(PRODUCTION_LIKE)));
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderPanel();
    await waitFor(() => expect(tile("League average bid").value).toBe("$1"));
    expect(tile("Your FAAB").value).toBe("—");

    rerender(
      <ManualAddDrop
        rows={ROWS}
        selectedTeam={TEAM}
        sleeperTeams={[]}
        leagueKey="dynasty_main"
        settings={{}}
      />,
    );

    // Team-specific half now known; league half unchanged.
    expect(tile("Your FAAB")).toEqual({ value: "$63", meta: "of $100" });
    expect(tile("League average bid").value).toBe("$1");
    expect(tile("League median bid").value).toBe("$0");
    // The calculator controls appear with the team.
    expect(screen.getByLabelText("Search drop candidates")).toBeInTheDocument();
    // League analytics are keyed by league, not by team.
    // (The calculator's own trade meter makes unrelated reads once it mounts;
    // count only the analytics section.)
    const analyticsReads = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/public/league/faabAnalytics"),
    );
    expect(analyticsReads).toHaveLength(1);
  });

  it("still renders a $0 balance as $0 for a selected team (known, not missing)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(sectionEnvelope(PRODUCTION_LIKE))),
    );

    renderPanel({ selectedTeam: { ...TEAM, faabRemaining: 0 } });

    await waitFor(() => expect(tile("Your FAAB").value).toBe("$0"));
  });

  it("states a team with no reported balance as unknown, not $0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(sectionEnvelope(PRODUCTION_LIKE))),
    );

    renderPanel({ selectedTeam: { name: "Mine", players: [] } });

    await waitFor(() => expect(tile("League average bid").value).toBe("$1"));
    expect(tile("Your FAAB")).toEqual({ value: "—", meta: "balance not reported" });
  });

  it("still states an unavailable league read beside a known team balance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "nope" }, 503)));

    renderPanel({ selectedTeam: TEAM });

    await waitFor(() =>
      expect(tile("League average bid").meta).toBe("unavailable: HTTP 503"),
    );
    expect(tile("Your FAAB").value).toBe("$63");
    expect(tile("League median bid").value).toBe("—");
  });

  it("drops the previous league's figures when the league changes", async () => {
    let releaseSecond;
    const fetchMock = vi.fn((url) => {
      if (String(url).includes("leagueKey=dynasty_main")) {
        return Promise.resolve(jsonResponse(sectionEnvelope(PRODUCTION_LIKE)));
      }
      return new Promise((resolve) => {
        releaseSecond = () =>
          resolve(
            jsonResponse(
              sectionEnvelope({
                leagueBudget: 200,
                leagueAvgWinningBid: 9.6,
                leagueMedianWinningBid: 8,
                totalBidsAnalyzed: 30,
              }),
            ),
          );
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderPanel();
    await waitFor(() => expect(tile("League average bid").value).toBe("$1"));

    rerender(
      <ManualAddDrop
        rows={ROWS}
        selectedTeam={null}
        sleeperTeams={[]}
        leagueKey="dynasty_new"
        settings={{}}
      />,
    );

    // Pending: league A's "$1" must not linger under league B.
    await waitFor(() =>
      expect(tile("League average bid")).toEqual({ value: "—", meta: "loading…" }),
    );

    releaseSecond();
    await waitFor(() => expect(tile("League average bid").value).toBe("$10"));
    expect(tile("League median bid").value).toBe("$8");
  });

  it("holds the team-resolving skeleton: no league strip while team identity loads", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(sectionEnvelope(PRODUCTION_LIKE))),
    );

    renderPanel({ teamLoading: true });

    // The skeleton keeps the settled calculator's height (the /waivers CLS
    // fix); the strip appears with the settled panel, not before it.
    expect(screen.queryByText("League average bid")).not.toBeInTheDocument();
  });
});

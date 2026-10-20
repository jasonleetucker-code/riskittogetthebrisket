/**
 * Brisket Trade Advisor — components (spec §4, §5.2; owner amendment
 * 2026-10-20: fairness only).
 *
 * Renders the real shell, builder, picker, summary and result against the
 * spec §4 fixtures (produced by the backend lane from real responses) with
 * `fetch` routed per endpoint.  Covers selection, search, filters, the
 * server's value-free order rendered unchanged, add / remove, review,
 * analyze, every fairness result (FAIR TRADE / NOT FAIR / UNABLE TO
 * DETERMINE) with each team's own result and the perspective switch over
 * ONE response, 2/3/4-team routed trades, client-side preconditions
 * (send-and-receive, destinations), the stale-roster note, 409 / 429 / 503,
 * focus + the single live announcement, Back from a result, the flag-off
 * fallback, and that a non-allowlisted numeric field never reaches the DOM.
 */
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { act, configure, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Real lazy chunks + user-event flows: generous per-test budget so a loaded
// CI worker does not turn a slow render into a failure.
vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 5000 });

const nav = vi.hoisted(() => ({ search: "", push: null, replace: null }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

import TradeAdvisorShell from "@/app/league/sections/trade-advisor-shell.jsx";
import { classifyTeamsResult } from "@/lib/trade-advisor-client";

const FIX = path.resolve(__dirname, "..", "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));
const READY = classifyTeamsResult({ status: 200, data: fixture("teams.success") });
const player = (id, label, position) => ({
  id,
  kind: "player",
  label,
  side: "offense",
  position,
  nflTeam: "NYJ",
  evaluable: true,
});
const OTHER = {
  3: [player("p:303", "Charlie Back", "RB"), player("p:304", "Charlie End", "TE")],
  4: [player("p:402", "Delta Runner", "RB"), player("p:403", "Delta Wideout", "WR")],
};

let routes;
let calls;
function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
beforeEach(() => {
  nav.search = "";
  nav.push = vi.fn((href) => {
    nav.search = href.split("?")[1] || "";
  });
  nav.replace = vi.fn((href) => {
    nav.search = href.split("?")[1] || "";
  });
  try {
    window.sessionStorage.clear();
  } catch {
    /* ignore */
  }
  calls = [];
  routes = {
    teams: () => json(200, fixture("teams.success")),
    assets: (rid) => {
      if (String(rid) === "1") return json(200, fixture("assets.position_alpha"));
      if (String(rid) === "2") return json(200, fixture("assets.pick-ownership-unavailable"));
      return json(200, {
        ...fixture("assets.pick-ownership-unavailable"),
        rosterId: Number(rid),
        assets: OTHER[String(rid)],
      });
    },
    analyze: () => json(200, fixture("analyze.not-fair-two-team")),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, init = {}) => {
      calls.push({ url, init });
      const m = String(url).match(/trade-advisor\/teams\/([^/]+)\/assets\?sort=(\w+)/);
      if (m) return routes.assets(m[1], m[2]);
      if (String(url).endsWith("/trade-advisor/teams")) return routes.teams();
      if (String(url).endsWith("/trade-advisor/analyze")) return routes.analyze(JSON.parse(init.body));
      return json(404, {});
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

async function chooseTeam(user, label, optionName) {
  const input = screen.getByRole("combobox", { name: label });
  await user.click(input);
  const list = screen.getByRole("listbox", { name: label });
  await user.click(within(list).getByRole("option", { name: optionName }));
}

async function setupTwoTeams(user, props = {}) {
  const view = render(
    <TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} {...props} />,
  );
  await chooseTeam(user, "Your team", /The Alphas/);
  await screen.findByRole("heading", { name: /Select trade partner/ });
  await chooseTeam(user, "Trade partner", /The Bravos/);
  return view;
}

async function addFrom(user, panelIndex, labels) {
  const panel = screen.getByTestId(`advisor-panel-${panelIndex}`);
  await user.click(within(panel).getByRole("button", { name: "+ Add player or pick" }));
  const sheet = await screen.findByTestId("advisor-asset-sheet");
  await within(sheet).findByTestId("advisor-asset-list");
  for (const label of labels) {
    await user.click(within(sheet).getByRole("option", { name: new RegExp(label) }));
  }
  await user.click(within(sheet).getByRole("button", { name: "Done" }));
}

async function chooseCount(user, n) {
  const count = screen.getAllByRole("radiogroup", { name: "Teams involved" })[0];
  await user.click(within(count).getByRole("radio", { name: String(n) }));
}

async function buildTwoTeamTrade(user) {
  await setupTwoTeams(user);
  await addFrom(user, 0, ["Alpha Quarterback"]);
  await addFrom(user, 1, ["Bravo Star"]);
}

describe("team step", () => {
  it("server-provided teams render immediately with no fetch, and say what choosing a team does", () => {
    render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} />);
    expect(screen.getByRole("heading", { name: /Which team is yours\?/ })).toBeInTheDocument();
    expect(screen.getByText(/you can view every other team's result too/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Your team" })).toBeInTheDocument();
    expect(screen.getByText(/doesn't sign you in/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("choosing your team mirrors it into ?team= with replace (no history entry) and disables it as a partner", async () => {
    const user = userEvent.setup();
    render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} />);
    await chooseTeam(user, "Your team", /The Alphas/);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/league?team=1", { scroll: false }));
    expect(nav.push).not.toHaveBeenCalled();
    await screen.findByRole("heading", { name: /Select trade partner/ });
    await user.click(screen.getByRole("combobox", { name: "Trade partner" }));
    const taken = within(screen.getByRole("listbox", { name: "Trade partner" })).getByRole("option", {
      name: /The Alphas/,
    });
    expect(taken).toHaveAttribute("aria-disabled", "true");
    expect(taken).toHaveTextContent("in trade");
  });

  it("shows the stale-roster note when rosters are not current", () => {
    render(
      <TradeAdvisorShell bootstrap={classifyTeamsResult({ status: 200, data: fixture("teams.rosters-stale") })} />,
    );
    expect(screen.getByTestId("advisor-roster-freshness")).toHaveTextContent(
      `Rosters as of ${fixture("teams.rosters-stale").rosters.asOf}. Recent trades or roster moves may not appear yet.`,
    );
  });

  it("no server answer: asks from the browser; a disabled advisor falls back to Overview", async () => {
    routes.teams = () => json(503, fixture("error.disabled"));
    const onUnavailable = vi.fn();
    render(<TradeAdvisorShell bootstrap={{ state: "unknown" }} onUnavailable={onUnavailable} />);
    await waitFor(() => expect(onUnavailable).toHaveBeenCalled());
  });

  it("no server answer and the browser fetch fails: an honest retry, not a broken page", async () => {
    routes.teams = () => json(500, {});
    const onOpenOverview = vi.fn();
    const user = userEvent.setup();
    render(
      <TradeAdvisorShell bootstrap={{ state: "unknown" }} onUnavailable={vi.fn()} onOpenOverview={onOpenOverview} />,
    );
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Go to the league overview" }));
    expect(onOpenOverview).toHaveBeenCalled();
    routes.teams = () => json(200, fixture("teams.success"));
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("combobox", { name: "Your team" })).toBeInTheDocument();
  });
});

describe("asset picker", () => {
  it("renders the server's order unchanged, filters without reordering, and blocks duplicates", async () => {
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await user.click(
      within(screen.getByTestId("advisor-panel-0")).getByRole("button", { name: "+ Add player or pick" }),
    );
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    const list = await within(sheet).findByTestId("advisor-asset-list");
    // Scoped to the asset listbox: the native <select>s carry options too.
    const names = () =>
      within(within(sheet).getByTestId("advisor-asset-list"))
        .getAllByRole("option")
        .map((o) => o.querySelector("span span").textContent);
    expect(names()).toEqual(fixture("assets.position_alpha").assets.map((a) => a.label));
    expect(list.querySelector("[aria-posinset],[aria-setsize]")).toBeNull();
    expect(calls.find((c) => String(c.url).includes("/teams/1/assets")).url).toMatch(/sort=position_alpha$/);
    // No value sort is offered at all (privacy M2).
    expect(within(sheet).queryByRole("combobox", { name: "Sort players" })).toBeNull();
    expect(within(sheet).getByText(/listed by position, then name/)).toBeInTheDocument();

    await user.click(within(sheet).getByRole("radio", { name: "Defense" }));
    expect(names()).toEqual(["Alpha Lineman", "Alpha Backer"]);
    expect(within(sheet).getByRole("option", { name: /Alpha Lineman/ })).toHaveTextContent("DL (DT/DE)");
    await user.click(within(sheet).getByRole("radio", { name: "Picks" }));
    expect(names()).toEqual(["2027 1st — Own", "2027 2nd — Originally Bravo"]);
    await user.click(within(sheet).getByRole("radio", { name: "All" }));
    await user.type(within(sheet).getByRole("searchbox"), "runner");
    expect(names()).toEqual(["Alpha Runner"]);
    await user.clear(within(sheet).getByRole("searchbox"));

    await user.click(within(sheet).getByRole("option", { name: /Alpha Quarterback/ }));
    expect(within(sheet).getByRole("status", { name: "" })).toBeTruthy();
    expect(within(sheet).getByText("Added Alpha Quarterback.")).toBeInTheDocument();
    const added = within(sheet).getByRole("option", { name: /Alpha Quarterback/ });
    expect(added).toHaveAttribute("aria-disabled", "true");
    await user.click(added); // no-op
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(within(screen.getByTestId("advisor-panel-0")).getAllByRole("listitem")).toHaveLength(1);
  });

  it("distinguishes 'nothing matches' from 'pick ownership unknown'", async () => {
    routes.assets = () => json(200, fixture("assets.pick-ownership-unavailable"));
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await user.click(
      within(screen.getByTestId("advisor-panel-1")).getByRole("button", { name: "+ Add player or pick" }),
    );
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    await within(sheet).findByTestId("advisor-asset-list");
    await user.click(within(sheet).getByRole("radio", { name: "Picks" }));
    expect(within(sheet).getByTestId("advisor-assets-empty")).toHaveTextContent(
      "Pick ownership for this team can't be confirmed right now, so picks aren't listed.",
    );
    await user.click(within(sheet).getByRole("radio", { name: "All" }));
    await user.type(within(sheet).getByRole("searchbox"), "zzz");
    expect(within(sheet).getByTestId("advisor-assets-empty")).toHaveTextContent(
      "No players or picks match this filter.",
    );
  });

  it("a list that fails to load shows its own error with Retry", async () => {
    routes.assets = () => json(500, {});
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await user.click(
      within(screen.getByTestId("advisor-panel-0")).getByRole("button", { name: "+ Add player or pick" }),
    );
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    expect(await within(sheet).findByRole("button", { name: "Try again" })).toBeInTheDocument();
    routes.assets = () => json(200, fixture("assets.position_alpha"));
    await user.click(within(sheet).getByRole("button", { name: "Try again" }));
    expect(await within(sheet).findByTestId("advisor-asset-list")).toBeInTheDocument();
  });
});

describe("review, analyze and result", () => {
  it("summarises the trade, requires each side to send, posts identities only, and renders the server's words", async () => {
    const user = userEvent.setup();
    await setupTwoTeams(user);
    const analyze = screen.getByRole("button", { name: "Analyze trade" });
    expect(analyze).toBeDisabled();
    await addFrom(user, 0, ["Alpha Quarterback"]);
    expect(screen.getByText(/The Bravos \(Bravo\) must also send at least one player or pick/)).toBeInTheDocument();
    await addFrom(user, 1, ["Bravo Star"]);
    const summary = screen.getByTestId("advisor-summary");
    expect(within(summary).getByTestId("advisor-flows-1")).toHaveTextContent("Alpha Quarterback → The Bravos (Bravo)");
    expect(within(summary).getByTestId("advisor-flows-1")).toHaveTextContent("Bravo Star ← The Bravos (Bravo)");
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const result = await screen.findByTestId("advisor-result");
    const post = calls.find((c) => c.init.method === "POST");
    expect(JSON.parse(post.init.body)).toEqual({
      perspectiveRosterId: 1,
      teams: [1, 2],
      assets: [
        { id: "p:101", from: 1, to: 2 },
        { id: "p:201", from: 2, to: 1 },
      ],
    });
    expect(post.init.credentials).toBe("omit");
    const raw = fixture("analyze.not-fair-two-team");
    expect(within(result).getByTestId("advisor-overall-label")).toHaveTextContent(raw.overall.label);
    expect(within(result).getByText(raw.overall.reasonText)).toBeInTheDocument();
    expect(within(result).getByTestId("advisor-team-verdict-label")).toHaveTextContent("NOT FAIR FOR THIS TEAM");
    expect(screen.getByRole("heading", { name: "Is this trade fair?" })).toHaveFocus();
    expect(within(result).getAllByRole("status")).toHaveLength(1);
    expect(nav.push).toHaveBeenCalledWith("/league?team=1&step=result", { scroll: false });
    // Fairness only: no accept / decline language and no personal advice.
    expect(result.textContent).not.toMatch(/\b(accept|decline|recommend\w*|should|approve|deny)\b/i);
  });

  it.each([
    ["analyze.fair-two-team", "FAIR TRADE", "positive", false],
    ["analyze.not-fair-two-team", "NOT FAIR", "warning", false],
    ["analyze.unable-asset", "UNABLE TO DETERMINE", "neutral", false],
    ["analyze.unable-stale-rosters", "UNABLE TO DETERMINE", "neutral", false],
  ])("%s renders the overall result %s verbatim with tone %s", async (name, label, tone, retry) => {
    routes.analyze = () => json(200, fixture(name));
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const result = await screen.findByTestId("advisor-result");
    expect(within(result).getByTestId("advisor-overall-label")).toHaveTextContent(label);
    expect(within(result).getByTestId("advisor-overall").getAttribute("data-tone")).toBe(tone);
    expect(Boolean(within(result).queryByRole("button", { name: "Try again" }))).toBe(retry);
    for (const t of fixture(name).teams) expect(within(result).getAllByText(t.label).length).toBeGreaterThan(0);
  });

  it("an asset that can't be valued is named on the team's own result", async () => {
    routes.analyze = () => json(200, fixture("analyze.unable-asset"));
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await addFrom(user, 0, ["Ghost Player"]);
    await addFrom(user, 1, ["Bravo Runner"]);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const view = await screen.findByTestId("advisor-team-view");
    expect(view).toHaveTextContent("Players or picks concerned: Ghost Player.");
    expect(view).toHaveTextContent(fixture("analyze.unable-asset").teams[0].reasonText);
  });

  it("Try again on a transient UNABLE resubmits the same trade", async () => {
    const transient = fixture("analyze.unable-asset");
    routes.analyze = () =>
      json(200, {
        ...transient,
        teams: transient.teams.map((t) => ({
          ...t,
          reasonCode: "evaluation_unavailable",
          reasonText: "This trade can't be evaluated reliably right now.",
          unavailableAssetIds: [],
        })),
      });
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    routes.analyze = () => json(200, fixture("analyze.not-fair-two-team"));
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("advisor-overall-label")).toHaveTextContent("NOT FAIR"));
    const posts = calls.filter((c) => c.init.method === "POST").map((c) => c.init.body);
    expect(posts).toHaveLength(2);
    expect(posts[0]).toBe(posts[1]);
  });

  it("Edit / New trade / Start over", async () => {
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    await user.click(screen.getByRole("button", { name: "Edit trade" }));
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Alpha Quarterback")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    await user.click(screen.getByRole("button", { name: "New trade" }));
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Nothing added yet.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Trade partner" })).toHaveValue("The Bravos");
    await user.click(
      within(screen.getByTestId("advisor-panel-0")).getByRole("button", { name: "+ Add player or pick" }),
    );
    await user.click(screen.getByRole("button", { name: "Done" }));
  });

  // Launch gate 8 (WCAG 2.4.3): the pressed button unmounts with the
  // result, so each action must move focus somewhere sensible — never
  // leave it on <body>.  Driven by keyboard (Enter on the focused button).
  it("focus after Edit trade / New trade / Start over lands on the step the reader was sent back to", async () => {
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    const press = async (name) => {
      screen.getByRole("button", { name }).focus();
      await user.keyboard("{Enter}");
    };
    await press("Analyze trade");
    await screen.findByTestId("advisor-result");
    expect(screen.getByRole("heading", { name: "Is this trade fair?" })).toHaveFocus();

    await press("Edit trade");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Build your trade/ })).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);

    await press("Analyze trade");
    await screen.findByTestId("advisor-result");
    await press("New trade");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Build your trade/ })).toHaveFocus());
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Nothing added yet.")).toBeInTheDocument();

    await addFrom(user, 0, ["Alpha Quarterback"]);
    await addFrom(user, 1, ["Bravo Star"]);
    await press("Analyze trade");
    await screen.findByTestId("advisor-result");
    await press("Start over");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Which team is yours\?/ })).toHaveFocus());
    expect(screen.getByRole("combobox", { name: "Your team" })).toHaveValue("");
    expect(screen.queryByTestId("advisor-panel-0")).toBeNull();
  });

  it("focus after Remove moves to the next asset, then the previous one, then that team's Add button", async () => {
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await addFrom(user, 0, ["Alpha Quarterback", "Alpha Runner", "Alpha Receiver"]);
    const panel = () => screen.getByTestId("advisor-panel-0");
    const remove = async (label) => {
      within(panel())
        .getByRole("button", { name: `Remove ${label}` })
        .focus();
      await user.keyboard("{Enter}");
    };
    await remove("Alpha Quarterback");
    await waitFor(() => expect(within(panel()).getByRole("button", { name: "Remove Alpha Runner" })).toHaveFocus());
    await remove("Alpha Receiver"); // the last one: focus steps back
    await waitFor(() => expect(within(panel()).getByRole("button", { name: "Remove Alpha Runner" })).toHaveFocus());
    await remove("Alpha Runner"); // none left: the team's Add button
    await waitFor(() => expect(within(panel()).getByRole("button", { name: "+ Add player or pick" })).toHaveFocus());
    expect(within(panel()).getByText("Nothing added yet.")).toBeInTheDocument();
  });

  it("Back from a result returns to the builder with the legs intact", async () => {
    const user = userEvent.setup();
    const view = await setupTwoTeams(user);
    await addFrom(user, 0, ["Alpha Quarterback"]);
    await addFrom(user, 1, ["Bravo Star"]);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    nav.search = "team=1"; // the browser's Back
    view.rerender(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} />);
    await waitFor(() => expect(screen.queryByTestId("advisor-result")).toBeNull());
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Alpha Quarterback")).toBeInTheDocument();
    nav.search = "team=1&step=result"; // and Forward
    view.rerender(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} />);
    expect(await screen.findByTestId("advisor-result")).toBeInTheDocument();
  });

  it("a reload re-shows a saved result only for the same board generation", async () => {
    const user = userEvent.setup();
    const view = await setupTwoTeams(user);
    await addFrom(user, 0, ["Alpha Quarterback"]);
    await addFrom(user, 1, ["Bravo Star"]);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    view.unmount();
    // Same generation: the reload lands back on the result.
    nav.search = "team=1&step=result";
    const same = render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} />);
    expect(await screen.findByTestId("advisor-result")).toBeInTheDocument();
    same.unmount();
    // The board moved on: the saved result is not presented as current.
    nav.search = "team=1&step=result";
    const moved = classifyTeamsResult({
      status: 200,
      data: { ...fixture("teams.success"), generation: "0000000000000000" },
    });
    render(<TradeAdvisorShell bootstrap={moved} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Analyze trade" })).toBeInTheDocument();
    expect(screen.queryByTestId("advisor-result")).toBeNull();
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Alpha Quarterback")).toBeInTheDocument();
  });

  it("a non-allowlisted numeric field never reaches the DOM", async () => {
    const SENT = "987654";
    routes.assets = (rid) => {
      const base =
        String(rid) === "1" ? fixture("assets.position_alpha") : fixture("assets.pick-ownership-unavailable");
      return json(200, {
        ...base,
        value: 987654,
        assets: base.assets.map((a) => ({ ...a, value: 987654, rankDerivedValue: 987654, rank: 1 })),
      });
    };
    const raw = fixture("analyze.not-fair-two-team");
    routes.analyze = () =>
      json(200, {
        ...raw,
        gap: 987654,
        confidence: 0.987654,
        overall: { ...raw.overall, gap: 987654, band: "lopsided" },
        teams: raw.teams.map((t) => ({ ...t, value: 987654, gap: -987654, category: "STRONGLY_UNFAVORABLE" })),
      });
    const user = userEvent.setup();
    const view = await setupTwoTeams(user);
    await addFrom(user, 0, ["Alpha Quarterback"]);
    await addFrom(user, 1, ["Bravo Star"]);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    expect(view.container.innerHTML).not.toContain(SENT);
    expect(document.body.innerHTML).not.toContain(SENT);
    expect(JSON.stringify(window.sessionStorage)).not.toContain(SENT);
    expect(document.body.innerHTML).not.toMatch(/lopsided|STRONGLY_UNFAVORABLE/);
  });
});

describe("errors", () => {
  it("409: explains, flags the moved asset and refetches the lists", async () => {
    routes.analyze = () => json(409, fixture("error.stale-assets"));
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    const before = calls.length;
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    expect(await screen.findByText("Rosters changed")).toBeInTheDocument();
    expect(within(screen.getByTestId("advisor-panel-1")).getByText(/No longer on this roster/)).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.slice(before).some((c) => c.url.endsWith("/trade-advisor/teams") && c.init.cache === "reload")).toBe(
        true,
      ),
    );
  });

  it("429: counts down and holds the Analyze button", async () => {
    routes.analyze = () => json(429, { ...fixture("error.rate-limited"), retryAfterSeconds: 2 });
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    expect(await screen.findByTestId("advisor-cooldown")).toHaveTextContent(/try again in 2s/);
    expect(screen.getByRole("button", { name: "Analyze trade" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Analyze trade" })).toBeEnabled(), { timeout: 4000 });
  });

  it("503 disabled mid-session hands the hub back to Overview", async () => {
    routes.analyze = () => json(503, fixture("error.disabled"));
    const onUnavailable = vi.fn();
    const user = userEvent.setup();
    await setupTwoTeams(user, { onUnavailable });
    await addFrom(user, 0, ["Alpha Quarterback"]);
    await addFrom(user, 1, ["Bravo Star"]);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await waitFor(() => expect(onUnavailable).toHaveBeenCalled());
  });

  it("503 not ready: retry offered, never a made-up answer", async () => {
    routes.analyze = () => json(503, fixture("error.not-ready"));
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    expect(await screen.findByText("No answer from the trade advisor")).toBeInTheDocument();
    expect(screen.queryByTestId("advisor-result")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  // Admission control on the analyze route (Lane C, R2-5): 503
  // advisor_unavailable with reason busy | timeout.  The bodies are the
  // route's shape; the server's message is deliberately NOT the one shown
  // (the client renders its own fixed copy, identical in wording).
  for (const [reason, title, copy] of [
    ["busy", "The trade advisor is busy", "The trade advisor is busy right now. Please try again in a moment."],
    ["timeout", "The trade advisor took too long", "The trade advisor took too long to answer. Please try again."],
  ]) {
    it(`503 ${reason}: fixed copy, the trade is kept, focus on Try again, and Try again resubmits it`, async () => {
      routes.analyze = () =>
        json(503, { error: "advisor_unavailable", reason, message: "server text 987654 must not render" });
      const user = userEvent.setup();
      await buildTwoTeamTrade(user);
      await user.click(screen.getByRole("button", { name: "Analyze trade" }));
      // A warning Banner is role="alert": announced, not only shown.
      const banner = (await screen.findByText(title)).closest('[role="alert"]');
      expect(banner).not.toBeNull();
      expect(banner).toHaveTextContent(copy);
      expect(banner).not.toHaveTextContent(/987654|server text/);
      expect(screen.queryByTestId("advisor-result")).toBeNull();
      // The trade the reader built is untouched.
      expect(within(screen.getByTestId("advisor-panel-0")).getByText("Alpha Quarterback")).toBeInTheDocument();
      expect(within(screen.getByTestId("advisor-panel-1")).getByText("Bravo Star")).toBeInTheDocument();
      // Keyboard: focus is on the banner's one action, never left on <body>.
      const retry = within(banner).getByRole("button", { name: "Try again" });
      await waitFor(() => expect(retry).toHaveFocus());
      // Keyboard activation resubmits the SAME trade and reaches the answer.
      routes.analyze = () => json(200, fixture("analyze.not-fair-two-team"));
      await user.keyboard("{Enter}");
      await waitFor(() => expect(screen.getByTestId("advisor-overall-label")).toHaveTextContent("NOT FAIR"));
      const posts = calls.filter((c) => c.init.method === "POST").map((c) => c.init.body);
      expect(posts).toHaveLength(2);
      expect(posts[0]).toBe(posts[1]);
      expect(screen.queryByText(title)).toBeNull();
    });
  }

  it("a repeated busy refusal re-focuses the new banner's Try again", async () => {
    routes.analyze = () => json(503, { error: "advisor_unavailable", reason: "busy" });
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toHaveFocus());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(calls.filter((c) => c.init.method === "POST")).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toHaveFocus());
    expect(screen.getByText("The trade advisor is busy")).toBeInTheDocument();
  });
});

describe("multi-team trades (3 and 4 teams, one response, every team's own result)", () => {
  it("builds a routed 3-team trade, keeps Analyze disabled until it is valid, and shows every team's result", async () => {
    routes.analyze = () => json(200, fixture("analyze.three-team-fair"));
    const user = userEvent.setup();
    render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} />);
    await chooseTeam(user, "Your team", /The Alphas/);
    await screen.findByRole("heading", { name: /Select trade partner/ });
    await chooseCount(user, 3);
    expect(screen.queryByText(/more than two teams yet/)).toBeNull();
    await chooseTeam(user, "Trade partner", /The Charlies/);
    await chooseTeam(user, "Team C", /The Deltas/);
    await addFrom(user, 0, ["Alpha Backer"]);
    await addFrom(user, 1, ["Charlie Back"]);
    await addFrom(user, 2, ["Delta Wideout"]);
    const analyze = screen.getByRole("button", { name: "Analyze trade" });
    expect(analyze).toBeDisabled();
    expect(screen.getByText("Choose where Alpha Backer goes.")).toBeInTheDocument();
    // A one-way route leaves a team that only sends: still refused.
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Alpha Backer to" }), "3");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Charlie Back to" }), "4");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Delta Wideout to" }), "3");
    expect(screen.getByText(/Your team must also receive at least one player or pick/)).toBeInTheDocument();
    expect(analyze).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Delta Wideout to" }), "1");
    // Each panel shows what that team receives, and from whom.
    expect(within(screen.getByTestId("advisor-panel-0")).getByText(/Delta Wideout/)).toBeInTheDocument();
    const summary = screen.getByTestId("advisor-summary");
    expect(summary).toHaveTextContent("Alpha Backer → The Charlies (Charlie)");
    expect(summary).toHaveTextContent("Delta Wideout ← The Deltas (Delta)");
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const result = await screen.findByTestId("advisor-result");
    const body = JSON.parse(calls.find((c) => c.init.method === "POST").init.body);
    expect(body.perspectiveRosterId).toBe(1);
    expect(body.teams).toEqual([1, 3, 4]);
    expect(body.assets.slice().sort((x, y) => (x.id < y.id ? -1 : 1))).toEqual(
      fixture("analyze.three-team-fair").trade,
    );
    expect(within(result).getByTestId("advisor-overall-label")).toHaveTextContent("FAIR TRADE");
    expect(within(result).getByText(fixture("analyze.three-team-fair").overall.note)).toBeInTheDocument();
    const rows = within(within(result).getByTestId("advisor-team-results")).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("The Alphas (Alpha) (your team)"),
      expect.stringContaining("The Charlies (Charlie)"),
      expect.stringContaining("The Deltas (Delta)"),
    ]);
    expect(result.textContent).not.toMatch(/available yet|unsupported/i);
  });

  it("4 teams: the perspective switch reads other rows of the SAME response (no new request)", async () => {
    routes.analyze = () => json(200, fixture("analyze.four-team-mixed"));
    const user = userEvent.setup();
    render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} />);
    await chooseTeam(user, "Your team", /The Bravos/);
    await screen.findByRole("heading", { name: /Select trade partner/ });
    await chooseCount(user, 4);
    await chooseTeam(user, "Trade partner", /The Alphas/);
    await chooseTeam(user, "Team C", /The Charlies/);
    await chooseTeam(user, "Team D", /The Deltas/);
    await addFrom(user, 0, ["Bravo Runner"]);
    await addFrom(user, 1, ["Alpha Backer"]);
    await addFrom(user, 2, ["Charlie Back"]);
    await addFrom(user, 3, ["Delta Runner"]);
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Bravo Runner to" }), "4");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Alpha Backer to" }), "3");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Charlie Back to" }), "1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Delta Runner to" }), "2");
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const result = await screen.findByTestId("advisor-result");
    expect(within(result).getByTestId("advisor-overall-label")).toHaveTextContent("NOT FAIR");
    const tabs = within(result).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      "The Bravos (Bravo) · Not fair",
      "The Alphas (Alpha) · Fair",
      "The Charlies (Charlie) · Fair",
      "The Deltas (Delta) · Not fair",
    ]);
    const view = within(result).getByTestId("advisor-team-view");
    expect(view.getAttribute("data-roster")).toBe("2");
    expect(within(view).getByTestId("advisor-team-verdict-label")).toHaveTextContent("NOT FAIR FOR THIS TEAM");
    const posts = () => calls.filter((c) => c.init.method === "POST").length;
    expect(posts()).toBe(1);
    await user.click(tabs[1]);
    expect(within(result).getByTestId("advisor-team-view").getAttribute("data-roster")).toBe("1");
    expect(within(result).getByTestId("advisor-team-verdict-label")).toHaveTextContent("FAIR FOR THIS TEAM");
    expect(within(result).getByTestId("advisor-team-view")).toHaveTextContent("Alpha Backer → The Charlies (Charlie)");
    expect(within(result).getByTestId("advisor-team-view")).toHaveTextContent("Charlie Back ← The Charlies (Charlie)");
    // Keyboard: arrow keys move between teams (roving tabindex).
    await user.keyboard("{ArrowRight}");
    expect(within(result).getByTestId("advisor-team-view").getAttribute("data-roster")).toBe("3");
    expect(posts()).toBe(1);
  });
});

describe("session persistence", () => {
  it("stores identities, labels and the fairness enums + fixed text only", async () => {
    const user = userEvent.setup();
    await buildTwoTeamTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    await act(async () => {});
    const saved = JSON.parse(window.sessionStorage.getItem("brisketAdvisor:v2"));
    expect(Object.keys(saved).sort()).toEqual(["legs", "result", "slots", "teamCount"]);
    expect(saved.result.overall.result).toBe("NOT_FAIR");
    expect(saved.result.teams.map((t) => t.result)).toEqual(["NOT_FAIR", "NOT_FAIR"]);
    expect(JSON.stringify(saved)).not.toMatch(/"(value|rank|score|gap|band|confidence)"/);
  });
});

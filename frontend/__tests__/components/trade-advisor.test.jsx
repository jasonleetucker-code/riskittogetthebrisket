/**
 * Brisket Trade Advisor — components (design §11 group E).
 *
 * Renders the real shell, builder, picker, summary and result against the
 * frozen §4 fixtures with `fetch` routed per endpoint.  Covers selection,
 * search, filters, the server order rendered unchanged, add / remove,
 * review, analyze, every result category (incl. the roster-limit copy),
 * Try again on UNAVAILABLE, the 3-team UNAVAILABLE multi_team_unsupported
 * state, the stale-roster note, 409 / 429 / 503, focus + the single live
 * announcement, Back from a result, the flag-off fallback, and that a
 * non-allowlisted numeric field never reaches the DOM.
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
    assets: (rid, sort) => {
      if (String(rid) === "1") return json(200, { ...fixture("assets.value_desc"), sort });
      if (String(rid) === "2") return json(200, { ...fixture("assets.alpha"), rosterId: 2, sort });
      return json(200, { ...fixture("assets.alpha"), rosterId: Number(rid), sort, assets: [{ id: "p:302", kind: "player", label: "Charlie Back", side: "offense", position: "RB", nflTeam: "NYJ", evaluable: true }] });
    },
    analyze: () => json(200, fixture("analyze.favorable")),
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
  const view = render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} onOpenOverview={vi.fn()} {...props} />);
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

async function buildFavorableTrade(user) {
  await setupTwoTeams(user);
  await addFrom(user, 0, ["Alpha Quarterback"]);
  await addFrom(user, 1, ["Bravo Star"]);
}

describe("team step", () => {
  it("server-provided teams render immediately with no fetch, and say the choice is a point of view", () => {
    render(<TradeAdvisorShell bootstrap={READY} onUnavailable={vi.fn()} />);
    expect(screen.getByRole("heading", { name: /Which team are you evaluating for\?/ })).toBeInTheDocument();
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
    const taken = within(screen.getByRole("listbox", { name: "Trade partner" })).getByRole("option", { name: /The Alphas/ });
    expect(taken).toHaveAttribute("aria-disabled", "true");
    expect(taken).toHaveTextContent("in trade");
  });

  it("shows the stale-roster note when rosters are not current", () => {
    render(<TradeAdvisorShell bootstrap={classifyTeamsResult({ status: 200, data: fixture("teams.rosters-stale") })} />);
    expect(screen.getByTestId("advisor-roster-freshness")).toHaveTextContent(
      "Rosters as of 2026-10-19. Recent trades or roster moves may not appear yet.",
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
    render(<TradeAdvisorShell bootstrap={{ state: "unknown" }} onUnavailable={vi.fn()} onOpenOverview={onOpenOverview} />);
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
    await user.click(within(screen.getByTestId("advisor-panel-0")).getByRole("button", { name: "+ Add player or pick" }));
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    const list = await within(sheet).findByTestId("advisor-asset-list");
    // Scoped to the asset listbox: the native <select>s carry options too.
    const names = () =>
      within(within(sheet).getByTestId("advisor-asset-list")).getAllByRole("option").map((o) => o.querySelector("span span").textContent);
    expect(names()).toEqual(fixture("assets.value_desc").assets.map((a) => a.label));
    expect(list.querySelector("[aria-posinset],[aria-setsize]")).toBeNull();
    expect(calls.find((c) => String(c.url).includes("/teams/1/assets")).url).toMatch(/sort=value_desc$/);

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

  it("changing the sort asks the server for that order", async () => {
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await user.click(within(screen.getByTestId("advisor-panel-1")).getByRole("button", { name: "+ Add player or pick" }));
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    await within(sheet).findByTestId("advisor-asset-list");
    await user.selectOptions(within(sheet).getByRole("combobox", { name: "Sort players" }), "alpha");
    await waitFor(() => expect(calls.some((c) => /teams\/2\/assets\?sort=alpha$/.test(c.url))).toBe(true));
  });

  it("distinguishes 'nothing matches' from 'pick ownership unknown'", async () => {
    routes.assets = () => json(200, fixture("assets.pick-ownership-unavailable"));
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await user.click(within(screen.getByTestId("advisor-panel-1")).getByRole("button", { name: "+ Add player or pick" }));
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    await within(sheet).findByTestId("advisor-asset-list");
    await user.click(within(sheet).getByRole("radio", { name: "Picks" }));
    expect(within(sheet).getByTestId("advisor-assets-empty")).toHaveTextContent(
      "Pick ownership for this team can't be confirmed right now, so picks aren't listed.",
    );
    await user.click(within(sheet).getByRole("radio", { name: "All" }));
    await user.type(within(sheet).getByRole("searchbox"), "zzz");
    expect(within(sheet).getByTestId("advisor-assets-empty")).toHaveTextContent("No players or picks match this filter.");
  });

  it("a list that fails to load shows its own error with Retry", async () => {
    routes.assets = () => json(500, {});
    const user = userEvent.setup();
    await setupTwoTeams(user);
    await user.click(within(screen.getByTestId("advisor-panel-0")).getByRole("button", { name: "+ Add player or pick" }));
    const sheet = await screen.findByTestId("advisor-asset-sheet");
    expect(await within(sheet).findByRole("button", { name: "Try again" })).toBeInTheDocument();
    routes.assets = () => json(200, fixture("assets.value_desc"));
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
    expect(screen.getByText(/must send at least one player or pick/)).toBeInTheDocument();
    await addFrom(user, 1, ["Bravo Star"]);
    const summary = screen.getByTestId("advisor-summary");
    expect(within(summary).getByText("You send").nextSibling).toHaveTextContent("Alpha Quarterback");
    expect(within(summary).getByText("You receive").nextSibling).toHaveTextContent("Bravo Star");
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
    expect(within(result).getByTestId("advisor-headline")).toHaveTextContent("ACCEPT — GOOD TRADE FOR YOUR TEAM");
    expect(within(result).getByText("Our analysis indicates this trade benefits your team.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trade analysis" })).toHaveFocus();
    expect(within(result).getAllByRole("status")).toHaveLength(1);
    expect(nav.push).toHaveBeenCalledWith("/league?team=1&step=result", { scroll: false });
  });

  it.each([
    ["analyze.strongly-unfavorable", "DECLINE — STRONGLY NOT RECOMMENDED", "warning", false],
    ["analyze.roster-limit", "DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE", "warning", false],
    ["analyze.unavailable-asset", "NO RECOMMENDATION", "neutral", true],
  ])("%s renders verbatim with tone %s", async (name, headline, tone, retry) => {
    routes.analyze = () => json(200, fixture(name));
    const user = userEvent.setup();
    await buildFavorableTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const result = await screen.findByTestId("advisor-result");
    expect(within(result).getByTestId("advisor-headline")).toHaveTextContent(headline);
    expect(result.querySelector("[data-tone]").getAttribute("data-tone")).toBe(tone);
    expect(Boolean(within(result).queryByRole("button", { name: "Try again" }))).toBe(retry);
    if (name === "analyze.roster-limit") {
      expect(within(result).getByText("Your team couldn't complete this trade under the roster limit.")).toBeInTheDocument();
    }
  });

  it("Try again on UNAVAILABLE resubmits the same trade", async () => {
    routes.analyze = () => json(200, fixture("analyze.unavailable-asset"));
    const user = userEvent.setup();
    await buildFavorableTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    routes.analyze = () => json(200, fixture("analyze.favorable"));
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("advisor-headline")).toHaveTextContent("ACCEPT — GOOD TRADE FOR YOUR TEAM"));
    const posts = calls.filter((c) => c.init.method === "POST").map((c) => c.init.body);
    expect(posts).toHaveLength(2);
    expect(posts[0]).toBe(posts[1]);
  });

  it("Edit / New trade / Start over", async () => {
    const user = userEvent.setup();
    await buildFavorableTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    await user.click(screen.getByRole("button", { name: "Edit trade" }));
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Alpha Quarterback")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    await user.click(screen.getByRole("button", { name: "New trade" }));
    expect(within(screen.getByTestId("advisor-panel-0")).getByText("Nothing added yet.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Trade partner" })).toHaveValue("The Bravos");
    await user.click(within(screen.getByTestId("advisor-panel-0")).getByRole("button", { name: "+ Add player or pick" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
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

  it("a non-allowlisted numeric field never reaches the DOM", async () => {
    const SENT = "987654";
    routes.assets = (rid, sort) => {
      const base = String(rid) === "1" ? fixture("assets.value_desc") : fixture("assets.alpha");
      return json(200, { ...base, sort, value: 987654, assets: base.assets.map((a) => ({ ...a, value: 987654, rankDerivedValue: 987654, rank: 1 })) });
    };
    routes.analyze = () => json(200, { ...fixture("analyze.favorable"), gap: 987654, confidence: 0.987654 });
    const user = userEvent.setup();
    const view = await setupTwoTeams(user);
    await addFrom(user, 0, ["Alpha Quarterback"]);
    await addFrom(user, 1, ["Bravo Star"]);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    expect(view.container.innerHTML).not.toContain(SENT);
    expect(document.body.innerHTML).not.toContain(SENT);
    expect(JSON.stringify(window.sessionStorage)).not.toContain(SENT);
  });
});

describe("errors", () => {
  it("409: explains, flags the moved asset and refetches the lists", async () => {
    routes.analyze = () => json(409, fixture("error.stale-assets"));
    const user = userEvent.setup();
    await buildFavorableTrade(user);
    const before = calls.length;
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    expect(await screen.findByText("Rosters changed")).toBeInTheDocument();
    expect(within(screen.getByTestId("advisor-panel-1")).getByText(/No longer on this roster/)).toBeInTheDocument();
    await waitFor(() => expect(calls.slice(before).some((c) => c.url.endsWith("/trade-advisor/teams") && c.init.cache === "reload")).toBe(true));
  });

  it("429: counts down and holds the Analyze button", async () => {
    routes.analyze = () => json(429, { ...fixture("error.rate-limited"), retryAfterSeconds: 2 });
    const user = userEvent.setup();
    await buildFavorableTrade(user);
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
    await buildFavorableTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    expect(await screen.findByText("No answer from the trade advisor")).toBeInTheDocument();
    expect(screen.queryByTestId("advisor-result")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("three-team trades", () => {
  it("builds a routed 3-team trade and shows the honest UNAVAILABLE multi_team_unsupported result", async () => {
    routes.analyze = () => json(200, fixture("analyze.multi-team-unsupported"));
    const user = userEvent.setup();
    await setupTwoTeams(user);
    const count = screen.getAllByRole("radiogroup", { name: "Teams involved" })[0];
    await user.click(within(count).getByRole("radio", { name: "3" }));
    expect(screen.getByText(/can't give a\s+recommendation for trades with more than two teams yet/)).toBeInTheDocument();
    await chooseTeam(user, "Team C", /The Charlies/);
    await addFrom(user, 0, ["Alpha Receiver"]);
    await addFrom(user, 1, ["Bravo Runner"]);
    await addFrom(user, 2, ["Charlie Back"]);
    expect(screen.getByRole("button", { name: "Analyze trade" })).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Alpha Receiver to" }), "2");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Bravo Runner to" }), "3");
    await user.selectOptions(screen.getByRole("combobox", { name: "Send Charlie Back to" }), "1");
    const summary = screen.getByTestId("advisor-summary");
    expect(summary).toHaveTextContent("Alpha Receiver → The Bravos (Bravo)");
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    const result = await screen.findByTestId("advisor-result");
    const body = JSON.parse(calls.find((c) => c.init.method === "POST").init.body);
    expect(body).toEqual({
      perspectiveRosterId: 1,
      teams: [1, 2, 3],
      assets: fixture("analyze.multi-team-unsupported").trade,
    });
    expect(within(result).getByText("Your team's recommendation")).toBeInTheDocument();
    expect(within(result).getByTestId("advisor-headline")).toHaveTextContent("NO RECOMMENDATION");
    expect(within(result).getByText("Recommendations for trades with more than two teams aren't available yet.")).toBeInTheDocument();
    expect(within(result).queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

describe("session persistence", () => {
  it("stores identities, labels and the result enum + text only", async () => {
    const user = userEvent.setup();
    await buildFavorableTrade(user);
    await user.click(screen.getByRole("button", { name: "Analyze trade" }));
    await screen.findByTestId("advisor-result");
    await act(async () => {});
    const saved = JSON.parse(window.sessionStorage.getItem("brisketAdvisor:v1"));
    expect(Object.keys(saved).sort()).toEqual(["legs", "result", "slots", "teamCount"]);
    expect(saved.result.category).toBe("FAVORABLE");
    expect(JSON.stringify(saved)).not.toMatch(/"(value|rank|score|gap|band|confidence)"/);
  });
});

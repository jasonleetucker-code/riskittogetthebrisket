import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ContestPanel from "@/components/dfs/ContestPanel";

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

const REPORT = {
  contest: {},
  report: {
    ok: true,
    errors: [],
    warnings: ["Rank 2 pays more than rank 1; unusual, not rewritten."],
    derived: {
      paidPlaces: 10,
      paidShare: 0.1,
      cashPrizeCents: 150000,
      firstPlaceCents: 100000,
      firstPlaceShareOfCash: 0.6667,
      minCashCents: 5000,
      payoutShape: { shape: "tournament" },
      economics: {
        state: "raked",
        effectiveRake: 0.25,
        note: "Underfilled, but prizes are still below fees collected: this is NOT an overlay.",
      },
      exactEvAllowed: true,
    },
    tiePreview: { state: "exact", eachCents: 55000 },
  },
  entryCap: {
    upperBound: null,
    missing: ["spendLimit"],
    binding: [],
    note: "This is the most you are allowed/able to enter, not how many you should.",
    recommendation: { state: "unavailable", reason: "Recommending a count needs contest EV." },
  },
};

const PRESETS = [
  {
    id: "large_field_gpp",
    label: "Large-field GPP",
    dimensions: { payoutShape: "tournament" },
    objective: { description: "Maximize expected payout minus fee" },
    unsupportedReason: "Needs a field model.",
  },
  {
    id: "fifty_fifty",
    label: "50/50",
    dimensions: { payoutShape: "fifty_fifty" },
    objective: { description: "Maximize P(cash)" },
    unsupportedReason: "Needs a field model.",
  },
];

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ContestPanel", () => {
  it("sends blanks as unknown (null), never 0, and shows the server's report", async () => {
    const calls = [];
    fetch.mockImplementation(async (url, init) => {
      const u = String(url);
      calls.push({ u, body: init?.body ? JSON.parse(init.body) : null });
      if (u.endsWith("/presets")) return json(200, { presets: PRESETS });
      if (u.endsWith("/contests")) return json(200, { contests: [] });
      if (u.endsWith("/contests/validate")) return json(200, REPORT);
      throw new Error(u);
    });
    render(<ContestPanel platform="draftkings" sport="nfl" format="classic" />);
    fireEvent.change(screen.getByLabelText("Contest name"), { target: { value: "Milly" } });
    fireEvent.change(screen.getByLabelText("Entry fee ($)"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Check contest" }));
    expect(await screen.findByText("Tournament (GPP)")).toBeInTheDocument();
    const sent = calls.find((c) => c.u.endsWith("/contests/validate")).body;
    expect(sent.contest.currentEntries).toBeNull();
    expect(sent.contest.existingUserEntries).toBeNull();
    expect(sent.contest.guaranteed).toBeNull();
    expect(sent.spendLimit).toBeNull();
    expect(screen.getByText(/NOT an overlay/)).toBeInTheDocument();
    expect(screen.getByText(/\$550\.00 each/)).toBeInTheDocument();
    expect(screen.getByText(/missing: spend limit/)).toBeInTheDocument();
    expect(screen.getByText(/Recommended count: unavailable/)).toBeInTheDocument();
    // Only presets that fit the derived shape, each labelled unavailable.
    expect(screen.getByText("Large-field GPP")).toBeInTheDocument();
    expect(screen.queryByText("50/50")).not.toBeInTheDocument();
    expect(screen.getByText("Not available yet")).toBeInTheDocument();
  });

  it("saves as a new version rather than overwriting", async () => {
    const calls = [];
    let saves = 0;
    fetch.mockImplementation(async (url, init) => {
      const u = String(url);
      const method = init?.method || "GET";
      calls.push({ u, method, body: init?.body ? JSON.parse(init.body) : null });
      if (u.endsWith("/presets")) return json(200, { presets: [] });
      if (u.endsWith("/contests") && method === "GET") return json(200, { contests: [] });
      if (u.endsWith("/contests")) {
        saves += 1;
        return json(201, { contestId: "contest_1", version: saves });
      }
      if (u.endsWith("/contests/validate")) return json(200, REPORT);
      throw new Error(u);
    });
    render(<ContestPanel platform="draftkings" sport="nfl" format="classic" />);
    fireEvent.change(screen.getByLabelText("Contest name"), { target: { value: "Milly" } });
    fireEvent.click(screen.getByRole("button", { name: "Save contest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save as version 2" }));
    await screen.findByRole("button", { name: "Save as version 3" });
    const posts = calls.filter((c) => c.method === "POST" && c.u.endsWith("/contests"));
    expect(posts[0].body.contestId).toBeNull();
    expect(posts[1].body.contestId).toBe("contest_1");
  });

  it("surfaces a refusal message", async () => {
    fetch.mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith("/presets") || u.endsWith("/contests")) return json(200, { presets: [], contests: [] });
      return json(422, { error: "PAYOUT_UNREADABLE", message: "Some payout lines could not be read." });
    });
    render(<ContestPanel platform="draftkings" sport="nfl" format="classic" />);
    fireEvent.click(screen.getByRole("button", { name: "Check contest" }));
    expect(await screen.findByText("Some payout lines could not be read.")).toBeInTheDocument();
  });
});

describe("ContestPanel — modes, concentration and curve", () => {
  it("Quick mode picks a preset, lifts it to the build context, and says it is not available yet", async () => {
    fetch.mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith("/presets")) return json(200, { presets: PRESETS });
      return json(200, { contests: [] });
    });
    const onContextChange = vi.fn();
    render(<ContestPanel platform="draftkings" sport="nfl" format="classic" onContextChange={onContextChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Quick" }));
    fireEvent.change(await screen.findByLabelText("Contest type"), { target: { value: "large_field_gpp" } });
    expect(onContextChange).toHaveBeenLastCalledWith({ contestId: null, presetId: "large_field_gpp" });
    expect(screen.getByText(/builds use the transparent projection baseline/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Import" }));
    expect(screen.getByText(/no DraftKings or FanDuel contest-file layout has been\s+verified/)).toBeInTheDocument();
  });

  it("shows top-1% concentration and a labelled log-scale payout curve", async () => {
    fetch.mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith("/presets")) return json(200, { presets: [] });
      if (u.endsWith("/contests")) return json(200, { contests: [] });
      return json(200, {
        ...REPORT,
        report: {
          ...REPORT.report,
          derived: {
            ...REPORT.report.derived,
            topOnePercentShareOfCash: 0.42,
            curve: [
              { rank: 1, prizeCents: 500000 },
              { rank: 10, prizeCents: 50000 },
              { rank: 200, prizeCents: 2500 },
            ],
          },
        },
      });
    });
    render(<ContestPanel platform="draftkings" sport="nfl" format="classic" />);
    fireEvent.click(screen.getByRole("button", { name: "Check contest" }));
    expect(await screen.findByText("42.0%")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Payout curve, log scale: rank 1 pays \$5,000\.00/ })).toBeInTheDocument();
  });
});

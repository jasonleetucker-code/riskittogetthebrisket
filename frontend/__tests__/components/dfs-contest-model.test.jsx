import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ContestModel from "@/components/dfs/ContestModel";
import Scorecards from "@/components/dfs/Scorecards";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const BUILD = { buildId: "b1", snapshot: { id: "s1" }, contest: { contestId: "c1", name: "Sunday Mini" } };
const ROW = {
  lineup: ["1", "2"],
  expectedProfitCents: 125,
  expectedPayoutSe: 40,
  pCash: { p: 0.21 },
  pWin: 0.0012,
  expectedCopies: 0.33,
};
const SIM = {
  sims: 800,
  perLineup: [ROW],
  portfolio: { expectedProfitCents: 125, expectedPayoutSe: 40, pCash: { p: 0.21 } },
  assumptions: ["3 player(s) use uncalibrated spread priors"],
  note: "Model output under stated assumptions — not evidence of profitability.",
};

describe("ContestModel", () => {
  it("explains what is needed when the build has no contest", () => {
    render(<ContestModel build={{ buildId: "b1" }} snapshotId="s1" athletes={[]} />);
    expect(screen.getByText(/save or pick a contest in step 3/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("simulates a build and shows outcomes with their assumptions and error", async () => {
    const fetchMock = vi.fn(async () => ok(SIM));
    vi.stubGlobal("fetch", fetchMock);
    render(<ContestModel build={BUILD} snapshotId="s1" athletes={[{ player_id: "1", name: "Syn QB" }, { player_id: "2", name: "Syn WR" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Simulate this build" }));
    await screen.findByText("Syn QB, Syn WR");
    expect(screen.getAllByText("$1.25 ± $0.40").length).toBeGreaterThan(0);
    expect(screen.getByText("0.12%")).toBeTruthy();
    expect(screen.getByText("3 player(s) use uncalibrated spread priors")).toBeTruthy();
    expect(screen.getByText(/not evidence of profitability/)).toBeTruthy();
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent).toMatchObject({ buildId: "b1", contestId: "c1", allowPriors: false });
  });

  it("asks for a bankroll with the growth objective and reports the portfolio decision", async () => {
    const fetchMock = vi.fn(async () =>
      ok({
        candidates: 24,
        selection: { recommendedEntries: 1 },
        vsProjectionBaseline: { profitDifferenceCents: 30, profitDifferenceSe: 55 },
        decisionId: "decision_x",
        timing: "pre_lock",
        result: SIM,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<ContestModel build={BUILD} snapshotId="s1" athletes={[]} />);
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "log_growth" } });
    fireEvent.change(screen.getByLabelText("Bankroll ($)"), { target: { value: "200" } });
    fireEvent.click(screen.getByRole("button", { name: "Optimize a portfolio for this contest" }));
    await screen.findByText(/Decision decision_x recorded \(pre lock\)/);
    expect(screen.getByText(/at most 1 entry/)).toBeTruthy();
    expect(screen.getByText(/a within-model comparison/)).toBeTruthy();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ objective: "log_growth", bankroll: "200", entries: 3 });
  });
});

describe("Scorecards", () => {
  it("lists evaluations with their sample size and flags small samples", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        ok({
          evaluations: [
            { evaluationId: "e1", kind: "ownership", subject: "srcA", n: 12, metrics: { mae: 3.21, bias: 1.1, spearman: 0.7, smallSample: true } },
          ],
        }),
      ),
    );
    render(<Scorecards />);
    await screen.findByText("srcA");
    expect(screen.getByText("12 (small)")).toBeTruthy();
    expect(screen.getByText("3.21")).toBeTruthy();
  });

  it("shows an honest empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ evaluations: [] })));
    render(<Scorecards />);
    await screen.findByText("No evaluations yet");
  });
});

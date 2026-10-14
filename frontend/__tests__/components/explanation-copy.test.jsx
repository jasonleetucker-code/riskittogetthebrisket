/**
 * Explanation copy on /trade, /game-day and the public /league awards.
 *
 * These pin the STATEMENTS, not the styling: each assertion is one sentence
 * the page makes to a user and the code fact that makes it true.  When the
 * math changes, the matching assertion here should fail and the copy in
 * components/help/* change with it — that is the point.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { meterVerdict, ktcAdjustPackage } from "@/lib/trade-logic";
import TradeMeter from "@/components/trade/TradeMeter";
import TradeFairnessExplanation from "@/components/trade/TradeFairnessExplanation";
import {
  RECOMMENDATION_ONLY_TEXT,
  TradeVerdictHelp,
  ValueAdjustmentTip,
} from "@/components/help/TradeHelp";
import {
  BeatMedianTip,
  GameDayHowItWorks,
  ScoreNowTip,
  WinChanceTip,
} from "@/components/help/GameDayHelp";
import { AwardsHowItWorks } from "@/components/help/AwardsHelp";
import { _renderPlainSummary } from "@/components/ui/MonteCarloButton";
import { SUGGESTION_RAIL_LABELS } from "@/app/trade/trade-sections";
import { SimulationPanel } from "@/app/trade/trade-simulation-panel";
import { confidenceMeta } from "@/app/trade/trade-suggestions-desk";

async function openHelp(user, buttonName, dialogName) {
  await user.click(screen.getByRole("button", { name: buttonName }));
  const dialog = screen.getByRole("dialog", { name: dialogName });
  // The trade body is code-split (React.lazy) to keep /trade under its
  // chunk budget; wait for real content rather than the skeleton.
  // Generous timeout: under a loaded full-suite run the lazy chunk can take
  // longer than findAllByRole's 1 s default (measured flake, 2026-09-30).
  await within(dialog).findAllByRole("heading", { level: 3 }, { timeout: 10000 });
  return dialog;
}

const sides = [
  { id: 0, label: "A", assets: [] },
  { id: 1, label: "B", assets: [] },
];

describe("trade verdict wording follows the side model", () => {
  it("on /trade names the bigger PACKAGE and the team that receives it", () => {
    // Each 2-team side lists what that team SENDS (computeSideFlowAssets),
    // so the bigger package is the side giving up more.
    render(
      <TradeMeter
        sides={sides}
        sideTotals={[{ adjusted: 5000 }, { adjusted: 4000 }]}
        sidesSend
      />,
    );
    expect(
      screen.getByText("Side A's package is worth 20% more — Side B receives more value"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/wins by/)).toBeNull();
  });

  it("keeps the original wording where sides are not an exchange (/waivers)", () => {
    render(<TradeMeter sides={sides} sideTotals={[{ adjusted: 4000 }, { adjusted: 5000 }]} />);
    expect(screen.getByText("Side B wins by 20%")).toBeInTheDocument();
  });

  it("the fairness explanation calls the per-source numbers raw", () => {
    const a = { name: "X", sourceRankMeta: { ktc: { valueContribution: 5200 } } };
    const b = { name: "Y", sourceRankMeta: { ktc: { valueContribution: 4000 } } };
    render(
      <TradeFairnessExplanation
        sides={[{ label: "A", assets: [a] }, { label: "B", assets: [b] }]}
        sideTotals={[{ adjusted: 5000 }, { adjusted: 4000 }]}
      />,
    );
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("Side A's package is worth 20% more after adjustments.");
    expect(note.textContent).toContain("(raw)");
    expect(note.textContent).not.toMatch(/leans by|winning by/);
  });
});

describe("Monte Carlo summary on /trade names the package, not a winner", () => {
  it("a bigger Side A package means Side B receives more", () => {
    const s = _renderPlainSummary({ winProbA: 0.9, nSims: 2000 }, sides, true);
    expect(s.headline).toBe("Side A's package is clearly worth more.");
    expect(s.subline).toContain("Side B would receive more value");
    expect(s.tone).toBe("strong");
  });
  it("keeps the original wording off /trade", () => {
    expect(_renderPlainSummary({ winProbA: 0.9, nSims: 2000 }, sides).headline).toBe(
      "Side A is the clear winner.",
    );
  });
});

describe("TradeVerdictHelp — one explanation, matching the code", () => {
  it("states the badge bands meterVerdict actually uses", async () => {
    const user = userEvent.setup();
    render(<TradeVerdictHelp />);
    const dialog = await openHelp(user, /How the verdict works/, "How the trade verdict works");
    const text = dialog.textContent;
    // Boundaries named in the copy are exactly where meterVerdict changes.
    for (const [below, label, at, next] of [
      [349, "FAIR", 350, "SLIGHT EDGE"],
      [899, "SLIGHT EDGE", 900, "UNFAIR"],
      [1799, "UNFAIR", 1800, "LOPSIDED"],
    ]) {
      expect(meterVerdict(below).label).toBe(label);
      expect(meterVerdict(at).label).toBe(next);
      expect(text).toContain(label);
    }
    expect(text).toContain("FAIR under 350");
    expect(text).toContain("SLIGHT EDGE under 900");
    expect(text).toContain("UNFAIR under 1,800");
    expect(text).toContain("under 3%");
    expect(text).toContain(RECOMMENDATION_ONLY_TEXT);
  });

  it("explains that sides list what each team sends", async () => {
    const user = userEvent.setup();
    render(<TradeVerdictHelp />);
    const dialog = await openHelp(user, /How the verdict works/, "How the trade verdict works");
    expect(within(dialog).getByText(/Each side lists what that team/)).toBeInTheDocument();
    expect(dialog.textContent).toMatch(/Not included yet: competitive posture/);
  });

  it("never implies the site executes a trade", async () => {
    const user = userEvent.setup();
    render(<TradeVerdictHelp />);
    const dialog = await openHelp(user, /How the verdict works/, "How the trade verdict works");
    expect(dialog.textContent).not.toMatch(/\bwe will\b|automatically (send|accept|execute)/i);
    expect(RECOMMENDATION_ONLY_TEXT).toMatch(/never proposes, sends or accepts/);
  });
});

describe("ValueAdjustmentTip", () => {
  it("describes the gates ktcAdjustPackage applies, not a roster-spot bonus", async () => {
    const user = userEvent.setup();
    render(<ValueAdjustmentTip />);
    await user.click(screen.getByRole("button", { name: "What is Value Adjustment (VA)?" }));
    const region = screen.getByRole("region", { name: "Value Adjustment (VA)" });
    expect(region.textContent).toContain("Never applied to a 1-for-1");
    expect(region.textContent).toContain("3.3%");
    expect(region.textContent).not.toMatch(/roster spot/i);
    // The gates are real: 1-for-1 never adjusts; a 2-for-1 can.
    expect(ktcAdjustPackage([8000], [4000]).displayed).toBe(false);
    expect(ktcAdjustPackage([8000], [4000, 4000]).displayed).toBe(true);
  });
});

describe("SimulationPanel — capacity and totals copy", () => {
  const base = {
    team: { name: "My Team" },
    before: { totalValue: 1000 },
    after: { totalValue: 1200 },
    delta: { totalValue: 200, byPosition: {} },
    equity: 200,
    unresolvedIn: [],
    unresolvedOut: [],
  };

  it("says when roster capacity could not be computed, instead of vanishing", () => {
    render(
      <SimulationPanel
        simResult={{
          ...base,
          rosterCapacity: { unavailable: "RuntimeError", notes: ["x"] },
        }}
      />,
    );
    expect(screen.getByText(/could not be checked for this trade/)).toBeInTheDocument();
  });

  it("names unpriced forced releases rather than folding them into the value", () => {
    render(
      <SimulationPanel
        simResult={{
          ...base,
          rosterCapacity: {
            requiresDrops: true,
            rosterLimit: 58,
            forcedDropValue: 400,
            unpricedForcedDrops: 1,
            forcedDrops: [
              { playerId: "1", name: "Priced Guy", position: "WR", value: 400 },
              { playerId: "2", name: "Unknown Guy", position: "RB", value: null },
            ],
          },
        }}
      />,
    );
    expect(screen.getByText(/plus 1 unpriced, not counted/)).toBeInTheDocument();
  });

  it("labels the roster totals as raw board sums", () => {
    render(<SimulationPanel simResult={base} />);
    expect(screen.getByText(/summed board values, before Value Adjustment/)).toBeInTheDocument();
  });
});

describe("suggestion labels describe what the generators do", () => {
  it("coverage, not consensus", () => {
    expect(confidenceMeta("high").label).toBe("6+ sources");
    expect(confidenceMeta("medium").label).toBe("3–5 sources");
    expect(confidenceMeta("low").label).toBe("Under 3 sources");
  });
  it("no peak or undervaluation claim", () => {
    expect(SUGGESTION_RAIL_LABELS.sellHigh.hint).not.toMatch(/peaked/);
    expect(SUGGESTION_RAIL_LABELS.buyLow.hint).not.toMatch(/undervalued/i);
  });
});

describe("Game Day tips", () => {
  it("Score now names the lineup rule the league actually plays", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ScoreNowTip bestBall={false} />);
    await user.click(screen.getByRole("button", { name: "What is Score now?" }));
    expect(screen.getByRole("region", { name: "Score now" }).textContent).toContain(
      "the starters submitted on Sleeper",
    );
    unmount();
    render(<ScoreNowTip bestBall />);
    await user.click(screen.getByRole("button", { name: "What is Score now?" }));
    expect(screen.getByRole("region", { name: "Score now" }).textContent).toContain("(best ball)");
  });

  it("Win chance is a strict-ahead share with ties separate, and says it is unvalidated", async () => {
    const user = userEvent.setup();
    render(<WinChanceTip />);
    await user.click(screen.getByRole("button", { name: "What is Win chance?" }));
    const text = screen.getByRole("region", { name: "Win chance" }).textContent;
    expect(text).toContain("strictly ahead");
    expect(text).toContain("Ties are counted separately");
    expect(text).toContain("has not been published yet");
  });

  it("Beat median: exactly on the median is a tie, not a win", async () => {
    const user = userEvent.setup();
    render(<BeatMedianTip />);
    await user.click(screen.getByRole("button", { name: "What is Beat median?" }));
    expect(screen.getByRole("region", { name: "Beat median" }).textContent).toContain(
      "a tie, not a win",
    );
  });

  it("states no simulation count (the served count lives in Data info)", async () => {
    // matchup_intel.DEFAULT_DRAWS (2,000) is what is served, not
    // game_day_sim's 10,000 default; a literal here drifted once already.
    const user = userEvent.setup();
    render(<GameDayHowItWorks />);
    const dialog = await openHelp(user, /How this works/, "How Game Day works");
    expect(dialog.textContent).not.toMatch(/\d[\d,]* simulated weeks/);
  });

  it("How it works: pauses are league-wide and nothing is set on Sleeper", async () => {
    const user = userEvent.setup();
    render(<GameDayHowItWorks />);
    const dialog = await openHelp(user, /How this works/, "How Game Day works");
    expect(dialog.textContent).toContain("the forecast pauses for every team");
    expect(dialog.textContent).toContain("never assumed to be in progress");
    expect(dialog.textContent).toContain("never sets a lineup or makes a move on Sleeper");
  });
});

describe("AwardsHowItWorks", () => {
  it("describes the live rules: MVP .500-or-better gate, ungated Manager of the Year", async () => {
    const user = userEvent.setup();
    render(<AwardsHowItWorks />);
    const dialog = await openHelp(user, /How awards work/, "How the awards are decided");
    const text = dialog.textContent;
    expect(text).toContain(".500 or better");
    expect(text).not.toMatch(/above \.500|winning record/);
    expect(text).toContain("30% final finish, 25%");
    expect(text).toContain("no record or playoff requirement");
    expect(text).toContain("current leader, not the winner");
  });
});

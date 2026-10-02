/**
 * BDVM partial-scoring notice (#1555 Batch 2 Lane 6, decision D).
 *
 * The wording is the contract: a projection that cannot score some card
 * rules is a PARTIAL total whose omission may be positive OR negative. It is
 * never described as a lower bound — an unscored penalty makes the true
 * total lower — and an unpublished sign is never assumed to be a bonus.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import BdvmScoringNotice from "@/components/BdvmScoringNotice";
import { bdvmScoringCoverage, buildBdvmValueRows } from "@/lib/bdvm";

const PRE_1574 = {
  meta: {
    scoringCoverage: {
      unscoredKeys: { bonus_rec_te: 40, idp_tkl_loss: 12 },
      // The pre-#1574 backend note says "lower bound" — it must not be shown.
      note: "those players' projected points are a lower bound by these rules.",
    },
  },
};

const WITH_SIGNS = {
  meta: {
    scoringCoverage: {
      unscoredKeys: { bonus_rec_te: 40, pass_int_td: 3, mystery_rule: 1 },
      weightSign: { bonus_rec_te: "+", pass_int_td: "-", mystery_rule: null },
    },
  },
};

describe("bdvmScoringCoverage", () => {
  it("returns null without a census", () => {
    expect(bdvmScoringCoverage({ meta: {} })).toBeNull();
    expect(bdvmScoringCoverage(null)).toBeNull();
  });

  it("reports per-rule counts and signs; an absent sign is unknown, not a bonus", () => {
    const cov = bdvmScoringCoverage(WITH_SIGNS);
    expect(cov.signsPublished).toBe(true);
    expect(cov.anyPenalty).toBe(true);
    expect(cov.keys).toEqual([
      { key: "bonus_rec_te", players: 40, sign: "+" },
      { key: "pass_int_td", players: 3, sign: "-" },
      { key: "mystery_rule", players: 1, sign: null },
    ]);
    expect(bdvmScoringCoverage(PRE_1574).signsPublished).toBe(false);
  });

  it("carries each player's unscored rules onto the board row", () => {
    const rows = buildBdvmValueRows(
      { players: [{ playerId: "p1", name: "A", projection: { unscoredKeys: ["bonus_rec_te"] }, tradeValue: {} }] },
      "balanced",
    );
    expect(rows[0].unscoredKeys).toEqual(["bonus_rec_te"]);
  });
});

describe("BdvmScoringNotice", () => {
  it("says partial totals may be positive OR negative and never 'lower bound'", () => {
    const { container } = render(<BdvmScoringNotice payload={PRE_1574} />);
    expect(screen.getByText("Partial scoring")).toBeInTheDocument();
    const text = container.textContent;
    expect(text).toMatch(/partial total/);
    expect(text).toMatch(/positive \(a bonus\) or negative \(a penalty\)/);
    expect(text).toMatch(/higher or lower/);
    expect(text.toLowerCase()).not.toContain("lower bound");
  });

  it("labels signs from #1574 per rule, and 'not published' before it", () => {
    const { container, rerender } = render(<BdvmScoringNotice payload={WITH_SIGNS} />);
    expect(container.textContent).toMatch(/bonus_rec_te — 40 players · bonus \(\+\)/);
    expect(container.textContent).toMatch(/pass_int_td — 3 players · penalty \(−\)/);
    expect(container.textContent).toMatch(/mystery_rule — 1 player · sign unknown/);
    rerender(<BdvmScoringNotice payload={PRE_1574} />);
    expect(container.textContent).toMatch(/bonus_rec_te — 40 players · sign not published/);
    expect(container.textContent.toLowerCase()).not.toContain("lower bound");
  });

  it("renders nothing when every rule scored", () => {
    const { container } = render(
      <BdvmScoringNotice payload={{ meta: { scoringCoverage: { unscoredKeys: {} } } }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

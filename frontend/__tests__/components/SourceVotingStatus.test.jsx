/**
 * SourceVotingStatus — owner directive 2026-10-19 §8 on Source Health and
 * Settings.  The states that must not blur:
 *   * a real block renders one row per source with the owner's labels and
 *     the plain-English reason, the detail one click away;
 *   * every one of the eight labels renders, as TEXT (never colour alone);
 *   * no block yet (before the backend publishes it) is an honest "not
 *     available yet" — no fabricated rows, no 0%.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import SourceVotingStatus from "@/components/SourceVotingStatus";
import { VOTING_STATUS_LABELS, VOTING_STATUS_ORDER } from "@/lib/source-voting-status";
import fixture from "../fixtures/source-voting-status-2026-10-19.json";

function bodyRows(table) {
  return within(table)
    .getAllByRole("row")
    .filter((tr) => tr.closest("tbody"));
}

/** One entry per status, carrying the status CODE only (no statusLabel). */
function oneOfEach() {
  return {
    version: "source-voting-status/v1",
    asOf: "2026-10-19T05:23:48Z",
    freshnessSchedule: "v2_step_schedule",
    freshnessApplied: true,
    sources: VOTING_STATUS_ORDER.map((status, i) => ({
      key: `src_${status}`,
      displayName: `Source ${i + 1}`,
      status,
      reason: `Reason for ${status}.`,
      baseWeight: 1,
      effectiveWeight: status.startsWith("active_") ? Number(status.slice(7)) / 100 : 0,
      freshnessPct: status.startsWith("active_") ? Number(status.slice(7)) : null,
      lastGenuineUpdate: null,
      lastGenuineUpdateBasis: "unknown",
      voting: status.startsWith("active_"),
    })),
  };
}

describe("SourceVotingStatus", () => {
  it("renders one row per source with the server's labels and reasons", () => {
    render(<SourceVotingStatus block={fixture} />);
    const table = screen.getByRole("table");
    expect(bodyRows(table)).toHaveLength(fixture.sources.length);

    for (const header of ["Source", "Last Updated", "Freshness", "Voting Weight", "Status"]) {
      expect(within(table).getByRole("columnheader", { name: new RegExp(header) })).toBeTruthy();
    }

    const idptc = screen.getByTestId("source-voting-status-idpTradeCalc");
    expect(within(idptc).getByText("Active — 75%")).toBeTruthy();
    expect(within(idptc).getByText(/votes at 75% of its base weight/)).toBeTruthy();

    const stale = screen.getByTestId("source-voting-status-idpShowCombined");
    expect(within(stale).getByText("Stale — Not Voting")).toBeTruthy();
    expect(within(stale).getByText(/older than 30 days/)).toBeTruthy();

    const summary = screen.getByTestId("source-voting-summary");
    expect(summary.textContent).toMatch(/17\s+of\s+26\s+sources voting/);
    expect(summary.textContent).toContain("Oct 19, 2026");
    expect(screen.getByText(/0–7 days 100%/)).toBeTruthy();
  });

  it("shows every owner label as text, with the dot only decorative", () => {
    render(<SourceVotingStatus block={oneOfEach()} />);
    for (const status of VOTING_STATUS_ORDER) {
      const cell = screen.getByTestId(`source-voting-status-src_${status}`);
      const label = VOTING_STATUS_LABELS[status];
      // The label is readable text inside the status cell…
      expect(within(cell).getByText(label)).toBeTruthy();
      // …and the coloured dot carries no meaning of its own.
      for (const dot of cell.querySelectorAll(".ds-status-dot")) {
        expect(dot.getAttribute("aria-hidden")).toBe("true");
      }
    }
  });

  it("the server's statusLabel wins over the frontend map", () => {
    const block = {
      sources: [{ key: "a", status: "active_100", statusLabel: "Server label", reason: "r" }],
    };
    render(<SourceVotingStatus block={block} />);
    expect(within(screen.getByTestId("source-voting-status-a")).getByText("Server label")).toBeTruthy();
    expect(screen.queryByText("Active — 100%")).toBeNull();
  });

  it("no block yet is honest: not available, no rows, no 0%", () => {
    const { container } = render(<SourceVotingStatus block={null} />);
    expect(screen.getByTestId("source-voting-unavailable").textContent).toMatch(
      /Voting status not available yet/,
    );
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.textContent).not.toMatch(/0%/);
  });

  it("an empty or malformed block is not rendered as rows either", () => {
    const { rerender } = render(<SourceVotingStatus block={{ sources: [] }} />);
    expect(screen.getByTestId("source-voting-unavailable")).toBeTruthy();
    rerender(<SourceVotingStatus block={{ sources: "nope" }} />);
    expect(screen.getByTestId("source-voting-unavailable").textContent).toMatch(/could not be read/);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("loading without data shows a skeleton, not the unavailable state", () => {
    render(<SourceVotingStatus block={null} loading />);
    expect(screen.queryByTestId("source-voting-unavailable")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a failed fetch shows the failure, not an empty table", () => {
    render(
      <SourceVotingStatus
        block={null}
        failure={{ kind: "auth", message: "Sign in to continue.", retryable: false }}
        onRetry={() => {}}
      />,
    );
    expect(screen.queryByTestId("source-voting-unavailable")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("each row expands to plain detail and collapses again", () => {
    render(<SourceVotingStatus block={fixture} />);
    const toggle = screen.getByTestId("source-voting-toggle-idpTradeCalc");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toContain("IDP Trade Calculator");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const detailId = toggle.getAttribute("aria-controls");
    const detail = document.getElementById(detailId);
    expect(detail).toBeTruthy();
    const d = within(detail);
    expect(d.getByText("What would change this")).toBeTruthy();
    expect(d.getByText(/Returns to 100% of its base weight/)).toBeTruthy();
    expect(d.getByText(/based on the last time we saw its rankings actually change/)).toBeTruthy();
    expect(d.getByText("Rows not counted")).toBeTruthy();
    expect(d.getByText(/Set aside by the outlier filter/)).toBeTruthy();
    expect(d.getByText(/Offense 429 · IDP 377/)).toBeTruthy();
    expect(d.getByText(/Pick prices last updated Oct 10, 2026/)).toBeTruthy();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.getElementById(detailId)).toBeNull();
  });

  it("the detail shows a vote hold's owner decision", () => {
    render(<SourceVotingStatus block={fixture} />);
    const toggle = screen.getByTestId("source-voting-toggle-dlfIdp");
    fireEvent.click(toggle);
    const detail = within(document.getElementById(toggle.getAttribute("aria-controls")));
    expect(detail.getByText("Vote hold")).toBeTruthy();
    expect(detail.getByText(/DLF vote is offense-only/)).toBeTruthy();
    expect(detail.getByText(/Switch: dlf_offense_only_vote/)).toBeTruthy();
  });

  it("an unmeasured source reads Not measured everywhere, never 0%", () => {
    render(<SourceVotingStatus block={fixture} />);
    const mobile = screen.getByTestId("source-voting-mobile-signalsSf");
    expect(mobile.textContent).toContain("Updated Not tracked");
    expect(mobile.textContent).toContain("Freshness Not measured");
    expect(mobile.textContent).not.toMatch(/Freshness 0%/);
  });

  it("the folded mobile line carries the three hidden columns", () => {
    render(<SourceVotingStatus block={fixture} />);
    const mobile = screen.getByTestId("source-voting-mobile-idpTradeCalc");
    expect(mobile.textContent).toContain("Updated Oct 10, 2026 (8 days ago)");
    expect(mobile.textContent).toContain("Freshness 75%");
    expect(mobile.textContent).toContain("Weight 0.75");
  });

  it("says so when freshness weighting is switched off", () => {
    render(<SourceVotingStatus block={{ ...fixture, freshnessApplied: false }} />);
    expect(screen.getByRole("note").textContent).toMatch(/Freshness weighting is switched off/);
  });
});

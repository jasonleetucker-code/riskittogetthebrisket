/**
 * DLF IDP vote hold (owner directive 2026-10-16; since 2026-10-19 the
 * owner-approved restore, held at release pending the outlier-filter fix).
 *
 * The backend holds the DLF IDP boards from the vote by owner policy and
 * stamps them in ``privateSourceAvailability`` with ``holdKind:
 * "owner_policy"``, ``votes: false`` and ``voteState: "held"``.  The
 * Rankings source column must read that as "listed, not voting" — never as
 * "did not list this player" (held is not broken) — and never invent a value.
 */
import { describe, expect, it } from "vitest";

import { RANKING_SOURCES } from "@/lib/dynasty-data";
import { formatSourceCell } from "@/app/rankings/board-utils";
import { sourceVoteFields } from "@/lib/source-vote-state";

const DLF_IDP = RANKING_SOURCES.find((s) => s.key === "dlfIdp");

const HELD = {
  state: "present",
  provisioned: true,
  csvPresent: true,
  private: false,
  holdKind: "owner_policy",
  heldFromVote: "owner_policy_dlf_idp_restore_held_pending_outlier_fix",
  votes: false,
  voteState: "held",
};

describe("policy-held DLF IDP source", () => {
  it("is still a registered source in the frontend mirror", () => {
    expect(DLF_IDP).toBeTruthy();
    expect(RANKING_SOURCES.find((s) => s.key === "dlfRookieIdp")).toBeTruthy();
  });

  it("renders a listed player as 'not voting', not 'did not list'", () => {
    const row = { name: "Synthetic LB", pos: "LB", canonicalSites: { dlfIdp: 999150 } };
    const cell = formatSourceCell(row, DLF_IDP, {
      privateSourceAvailability: { dlfIdp: HELD },
    });
    expect(cell.hasVal).toBe(false);
    expect(cell.primary).toBe("—");
    expect(cell.mutedText).toBe("not voting");
    expect(cell.title).toContain("listed this player");
    expect(cell.title).toContain("Collected — not voting");
    expect(cell.title).not.toContain("did not list");
  });

  it("a player the held source did not list still reads as not listed", () => {
    const row = { name: "Synthetic LB", pos: "LB", canonicalSites: {} };
    const cell = formatSourceCell(row, DLF_IDP, {
      privateSourceAvailability: { dlfIdp: HELD },
    });
    expect(cell.title).toContain("did not list");
    expect(cell.mutedText).toBeUndefined();
  });

  it("the settings vote fields read held-by-policy as non-voting", () => {
    expect(sourceVoteFields(HELD)).toEqual({
      voteState: "held",
      nonVoting: true,
      voteLabel: "Collected — not voting",
    });
  });
});

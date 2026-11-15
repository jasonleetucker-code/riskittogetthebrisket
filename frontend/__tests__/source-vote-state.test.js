import { describe, expect, it } from "vitest";
import {
  VOTE_STATE_LABELS,
  sourceIsNonVoting,
  sourceVoteFields,
  sourceVoteState,
} from "@/lib/source-vote-state";

describe("source vote state (Settings + Rankings)", () => {
  it("reads the backend voteState verbatim", () => {
    expect(sourceVoteState({ voteState: "shadow", votes: false })).toBe(
      "shadow",
    );
    expect(sourceVoteState({ voteState: "active", votes: true })).toBe(
      "active",
    );
  });

  it("falls back for payloads that predate voteState", () => {
    expect(sourceVoteState({ votes: true })).toBe("active");
    expect(sourceVoteState({ votes: false, rolledBack: true })).toBe(
      "rolled_back",
    );
    expect(sourceVoteState({ votes: false, heldFromVote: true })).toBe("held");
    expect(sourceVoteState({ votes: false })).toBe("unavailable");
    expect(sourceVoteState(undefined)).toBe(null);
  });

  it("a public source (no availability entry) is a voting source", () => {
    expect(sourceVoteFields(undefined)).toEqual({
      voteState: null,
      nonVoting: false,
      voteLabel: null,
    });
    expect(sourceIsNonVoting(undefined)).toBe(false);
  });

  it("offense Signals voting keeps its controls", () => {
    const f = sourceVoteFields({ voteState: "active", votes: true });
    expect(f.nonVoting).toBe(false);
    expect(f.voteLabel).toBe("Active");
  });

  it("Signals IDP in shadow is non-voting with the owner label", () => {
    const f = sourceVoteFields({ voteState: "shadow", votes: false });
    expect(f.nonVoting).toBe(true);
    expect(f.voteLabel).toBe("Shadow — not voting");
    expect(VOTE_STATE_LABELS.held).toBe("Collected — not voting");
  });
});

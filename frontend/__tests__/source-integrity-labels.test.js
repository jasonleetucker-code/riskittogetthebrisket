// Outlier integrity v2 transparency (owner directive 2026-10-20 §10): the
// frontend LABELS the backend's per-observation category; it decides nothing,
// and a legitimate dissent never reads as invalid or corrupt.
import { describe, expect, it } from "vitest";

import {
  INTEGRITY_CATEGORY_LABELS,
  integrityCategoryLabel,
  integrityLabel,
  integrityReasonCategory,
  notVotingReasonLabel,
} from "../lib/source-voting-status";
import { rowSourceFreshness, sourceDroppedLabel } from "../lib/value-explainers";

describe("integrity category labels", () => {
  it("labels all ten directive §10 categories", () => {
    expect(Object.keys(INTEGRITY_CATEGORY_LABELS)).toHaveLength(10);
  });

  it("never labels valid dissent as invalid, corrupt or not voting", () => {
    const label = integrityCategoryLabel("valid_but_disagreeing").toLowerCase();
    for (const bad of ["invalid", "corrupt", "error", "not voting", "rejected"]) {
      expect(label).not.toContain(bad);
    }
    expect(integrityLabel({ status: "voting", primaryReason: "kept_dissent" })).toBe(
      INTEGRITY_CATEGORY_LABELS.valid_but_disagreeing,
    );
  });

  it("maps scoped reason codes by prefix and leaves unknown codes as themselves", () => {
    expect(integrityReasonCategory("normalization_scale_error@dlfSf/offense")).toBe(
      "normalization_scale_error",
    );
    expect(integrityReasonCategory("identity_contradicted:age")).toBe("invalid_player_identity");
    expect(integrityReasonCategory("held_pending_confirmation:observation_discontinuity")).toBe(
      "temporarily_held_by_policy",
    );
    expect(integrityReasonCategory("something_new")).toBeNull();
    expect(notVotingReasonLabel("something_new")).toBe("something_new");
    expect(notVotingReasonLabel("outlier_filter")).toBe("Set aside by the outlier filter");
    expect(notVotingReasonLabel("extreme_uncorroborated_tail")).toBe(
      INTEGRITY_CATEGORY_LABELS.rejected_by_integrity_rule,
    );
  });

  it("reads nothing into an observation with no integrity block", () => {
    expect(integrityLabel(null)).toBeNull();
    expect(integrityLabel({})).toBeNull();
  });
});

describe("per-row source list", () => {
  const row = {
    sourceRankMeta: {
      a: { weight: 1, appliedWeight: 1, integrity: { status: "voting", primaryReason: "voting", category: "voting_normally" } },
      b: {
        weight: 1,
        appliedWeight: 1,
        integrity: { status: "voting", primaryReason: "kept_dissent", category: "valid_but_disagreeing" },
      },
      c: {
        weight: 1,
        appliedWeight: 1,
        hampelDropped: true,
        integrity: {
          status: "rejected_tail",
          primaryReason: "extreme_uncorroborated_tail",
          category: "rejected_by_integrity_rule",
        },
      },
      d: { weight: 1, appliedWeight: 1, hampelDropped: true },
    },
  };
  const items = Object.fromEntries(rowSourceFreshness(row, {}).map((s) => [s.key, s]));

  it("keeps a dissenting source voting and marks it as dissent", () => {
    expect(items.b.voting).toBe(true);
    expect(items.b.dissent).toBe(true);
  });

  it("names why a Layer C vote was set aside", () => {
    expect(items.c.voting).toBe(false);
    expect(sourceDroppedLabel(items.c)).toBe(INTEGRITY_CATEGORY_LABELS.rejected_by_integrity_rule);
  });

  it("keeps the incumbent wording when no integrity block was stamped", () => {
    expect(items.d.integrityCategory).toBeNull();
    expect(sourceDroppedLabel(items.d)).toBe("dropped as an outlier");
  });
});

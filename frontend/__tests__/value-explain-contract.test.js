import { describe, expect, it } from "vitest";
import {
  exclusionReasonLabel,
  leaveOneOutReasonLabel,
  valueExplainView,
} from "@/lib/value-explain-contract";

describe("value-explain/v2 labels", () => {
  it("labels every exclusion reason the backend emits, and passes unknown ones through", () => {
    expect(exclusionReasonLabel("freshness_or_health_zero_weight", "excluded_stale_or_unhealthy")).toBe(
      "too stale or unhealthy to carry weight",
    );
    expect(exclusionReasonLabel("outlier:hampel", "hampel_outlier")).toBe(
      "dropped as an outlier (Hampel filter)",
    );
    expect(exclusionReasonLabel("outlier:joint_rank_gap", "hampel_outlier")).toBe(
      "dropped as an outlier (joint_rank_gap)",
    );
    expect(exclusionReasonLabel("superseded_by_family", "superseded_by_family")).toMatch(/provider family/);
    expect(exclusionReasonLabel("something_new", "x")).toBe("something_new");
    // A non-voter with no reason says so; a voter has no reason at all.
    expect(exclusionReasonLabel(null, "hampel_outlier")).toBe("reason not published");
    expect(exclusionReasonLabel(null, "voting")).toBeNull();
  });

  it("explains every unavailable leave-one-out reason", () => {
    for (const r of ["not_applicable", "no_voters", "mismatch", "fewer_than_two_voters"]) {
      expect(leaveOneOutReasonLabel(r)).not.toBe(r);
    }
    expect(leaveOneOutReasonLabel(undefined)).toBe("not available");
  });

  it("keeps missing numbers null — never 0 — and missing clocks null", () => {
    const v = valueExplainView({
      explainVersion: "value-explain/v2",
      modelSources: [{ source: "dlfSf", status: "voting", voteShare: null, clocks: {} }],
    });
    const s = v.sources[0];
    expect(s.voteShare).toBeNull();
    expect(s.contribution).toBeNull();
    expect(s.clocks.every((c) => c.at === null)).toBe(true);
    expect(s.treatment).toBe("unknown");
    expect(v.modelValue).toBeNull();
    expect(v.attributionExact).toBe(false);
    expect(v.leaveOneOut).toBeNull();
  });

  it("treats an absent per-source approximation flag as approximate", () => {
    const v = valueExplainView({ modelSources: [{ source: "dlfSf", status: "voting" }] });
    expect(v.sources[0].contributionIsApproximate).toBe(true);
    expect(v.isV2).toBe(false);
  });
});

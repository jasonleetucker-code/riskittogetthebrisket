/**
 * lib/model-lab.js — the Model Lab display materializer (IC-6).
 *
 * The fixture is a REAL `build_model_lab()` payload from main (see its
 * `_fixture` key), so these tests pin the materializer against the shape
 * the backend actually emits rather than a hand-written approximation.
 */
import { describe, expect, it } from "vitest";
import payload from "./fixtures/model-lab-payload.json";
import {
  challengerRows,
  challengerStateCounts,
  championVersion,
  familyListRows,
  findFamily,
  flagWord,
  formatInstant,
  humanizeKey,
  isFamilyId,
  isStateBlock,
  lastEvaluated,
  productionFlags,
  selectChallengers,
  servedStatement,
  stateBlockExtras,
} from "@/lib/model-lab";

const hill = () => findFamily(payload, "hill_scope_masters");

describe("state blocks", () => {
  it("recognises exactly the backend's vocabulary, with a reason", () => {
    expect(isStateBlock({ state: "unobserved", reason: "absent here" })).toBe(true);
    expect(isStateBlock({ state: "not_applicable", reason: "a rule" })).toBe(true);
    expect(isStateBlock({ state: "unmeasured", reason: "no monitor" })).toBe(true);
    // An empty reason is not a state block (model_lab.is_state_block).
    expect(isStateBlock({ state: "unobserved", reason: " " })).toBe(false);
    // receipts' "observed" is ordinary data, not missing data.
    expect(isStateBlock({ state: "observed", total: 0 })).toBe(false);
    expect(isStateBlock(0)).toBe(false);
    expect(isStateBlock(null)).toBe(false);
  });
});

describe("family list rows", () => {
  it("one row per family, champion and decision carried verbatim", () => {
    const rows = familyListRows(payload);
    expect(rows.map((r) => r.id)).toEqual(payload.families.map((f) => f.family));
    const h = rows.find((r) => r.id === "hill_scope_masters");
    expect(h.champion).toBe(2);
    expect(h.decision).toBe(hill().decisionReason);
  });

  it("a family with no served champion shows the backend's state block, never 0", () => {
    const ce = familyListRows(payload).find((r) => r.id === "consensus_edge");
    expect(isStateBlock(ce.champion)).toBe(true);
    expect(ce.champion.state).toBe("not_applicable");
  });

  it("an unobserved champion version stays unobserved", () => {
    const sparse = findFamily(payload, "sparse_evidence_estimator");
    expect(isStateBlock(championVersion(sparse.champion))).toBe(true);
  });

  it("lastEvaluation that is itself unobserved passes through as the at value", () => {
    const signals = findFamily(payload, "signals_idp_shared_market");
    const ev = lastEvaluated(signals.lastEvaluation);
    expect(isStateBlock(ev.at)).toBe(true);
    expect(ev.by).toBeNull();
  });
});

describe("challenger state counts", () => {
  it("are read from the backend, in lab-state order, and keep a real 0", () => {
    const counts = challengerStateCounts(hill(), payload.labStates);
    expect(counts.map((c) => c.state)).toEqual(payload.labStates);
    const shadow = counts.find((c) => c.state === "SHADOW");
    expect(shadow.count).toBe(0);
    expect(counts.find((c) => c.state === "CHAMPION").count).toBe(1);
  });

  it("an unobserved challenger list is a state block, not an empty list", () => {
    const fam = { family: "x", challengers: { state: "unobserved", reason: "builder failed" } };
    expect(isStateBlock(challengerRows(fam))).toBe(true);
    expect(selectChallengers(challengerRows(fam))).toEqual([]);
  });

  it("selection filters by state and shows newest first without copying rows", () => {
    const rows = challengerRows(hill());
    const all = selectChallengers(rows, "ALL");
    expect(all[0]).toBe(rows[rows.length - 1]);
    expect(all).toHaveLength(rows.length);
    const rejected = selectChallengers(rows, "REJECTED");
    expect(rejected.every((r) => r.state === "REJECTED")).toBe(true);
    expect(rejected).toHaveLength(hill().challengerStates.REJECTED);
  });
});

describe("served side", () => {
  it("reads a single top-level flag (shape on main)", () => {
    const ce = findFamily(payload, "consensus_edge");
    expect(productionFlags(ce.productionState)).toEqual([
      { flag: "consensus_edge", word: "OFF", reason: null },
    ]);
  });

  it("reads the flags list (#1708 shape) without listing a flag twice", () => {
    const ps = {
      flag: "sparse_evidence_estimator",
      enabled: true,
      flags: [
        { flag: "sparse_evidence_estimator", enabled: true },
        { flag: "joint_sparse_limited_evidence", state: "unobserved", reason: "flag unreadable" },
      ],
      servedNote: "candidate C is served: sparse_evidence_estimator ON",
    };
    expect(productionFlags(ps)).toEqual([
      { flag: "sparse_evidence_estimator", word: "ON", reason: null },
      { flag: "joint_sparse_limited_evidence", word: "Unobserved", reason: "flag unreadable" },
    ]);
    expect(servedStatement(ps)).toBe(ps.servedNote);
  });

  it("an unreadable flag is never OFF", () => {
    expect(flagWord({ flag: "f", state: "unobserved", reason: "boom" })).toBe("Unobserved");
    expect(flagWord({ flag: "f", enabled: false })).toBe("OFF");
  });

  it("served statement falls back to the plain `served` text (Hill)", () => {
    expect(servedStatement(hill().productionState)).toMatch(/eight constants/);
  });

  it("a spread, unreadable flag record still names its flag and keeps its siblings", () => {
    const ps = {
      flag: "consensus_edge",
      state: "unobserved",
      reason: "flag unreadable: OSError: locked",
      modelVersion: "ce.v0",
    };
    expect(productionFlags(ps)).toEqual([
      { flag: "consensus_edge", word: "Unobserved", reason: "flag unreadable: OSError: locked" },
    ]);
    // The flag carries the answer; the record is not collapsed into "served".
    expect(servedStatement(ps)).toBeNull();
    expect(stateBlockExtras(ps)).toEqual({ flag: "consensus_edge", modelVersion: "ce.v0" });
    expect(stateBlockExtras({ state: "unobserved", reason: "x" })).toBeNull();
  });

  it("the #1708 flags list is read even when the record itself is a state block", () => {
    const ps = {
      flag: "sparse_evidence_estimator",
      state: "unobserved",
      reason: "boom",
      servedNote: "served side unobserved",
      flags: [
        { flag: "sparse_evidence_estimator", state: "unobserved", reason: "boom" },
        { flag: "joint_sparse_limited_evidence", enabled: false },
      ],
    };
    expect(productionFlags(ps).map((f) => [f.flag, f.word])).toEqual([
      ["sparse_evidence_estimator", "Unobserved"],
      ["joint_sparse_limited_evidence", "OFF"],
    ]);
    expect(servedStatement(ps)).toBe("served side unobserved");
  });

  it("an unobserved productionState is returned as its block", () => {
    const blk = { state: "unobserved", reason: "builder failed" };
    expect(servedStatement(blk)).toBe(blk);
    expect(productionFlags(blk)).toEqual([]);
  });
});

describe("formatting helpers", () => {
  it("humanizes lower-camel keys only", () => {
    expect(humanizeKey("rowsPerHoldoutBoard")).toBe("Rows per holdout board");
    expect(humanizeKey("al0Verdict")).toBe("AL-0 verdict");
    expect(humanizeKey("rmse[FantasyCalc]")).toBe("rmse[FantasyCalc]");
    expect(humanizeKey("C1_conservative_reliability")).toBe("C1_conservative_reliability");
    expect(humanizeKey("FantasyCalc")).toBe("FantasyCalc");
  });

  it("formats only timezone-aware instants", () => {
    expect(formatInstant("2026-10-08T06:53:11.377237+00:00")).toBe("2026-10-08 06:53 UTC");
    expect(formatInstant("2026-10-01T14:17:33Z")).toBe("2026-10-01 14:17 UTC");
    expect(formatInstant("2026-09-30")).toBeNull();
    expect(formatInstant("unknown")).toBeNull();
  });

  it("family ids are snake_case only", () => {
    expect(isFamilyId("hill_scope_masters")).toBe(true);
    expect(isFamilyId("../status")).toBe(false);
    expect(isFamilyId("")).toBe(false);
  });
});

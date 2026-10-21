# Outlier integrity V2 / V2.1: documentation extraction note

**Status: provenance note only. It changes no rule, threshold, preregistration or verdict, and it
authorizes nothing.** Authorization stays with `docs/EXECUTION_PLAN.md`; product authority stays with
the owner hierarchy in `docs/MASTER_PRODUCT_PLAN.md`.

## What this change is

Every other file in this change is a **byte-for-byte copy** of the same path on the head of PR #1884
(`claude/outlier-integrity-v2`, head `58ed2ff8016b0c837616a9f96e224e143e890fcb`, 2026-10-21), carried
to `main` by itself so the research record is durable and reviewable apart from the code that
produced it. Nothing was edited, reformatted, renamed, summarized or re-wrapped. PR #1884 is neither
merged nor modified by this change.

Verify, from a clone with the PR head fetched (`git fetch origin pull/1884/head`):

    git diff --stat FETCH_HEAD -- docs/owner/OUTLIER_V21_O1_DECISION_2026-10-20.md \
        docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md \
        docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md \
        docs/sources/OUTLIER_INTEGRITY_V2_ARCHITECTURE.md \
        docs/sources/outlier_integrity_v2 \
        docs/sources/outlier_integrity_v21 ':!docs/sources/outlier_integrity_v21/EXTRACTION_NOTE.md'

The expected output is empty.

## What is here, by kind

| Kind | Files |
|---|---|
| Owner decision O-1 (see "Reconstructed wording" below) | `docs/owner/OUTLIER_V21_O1_DECISION_2026-10-20.md` |
| V2.1 preregistration (frozen rules, including the open owner question O-2 in section 12 and the identity-prerequisite readiness rule in section 3.7) | `docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md` |
| V2 preregistration and architecture | `docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`, `docs/sources/OUTLIER_INTEGRITY_V2_ARCHITECTURE.md` |
| Experiment manifests and frozen thresholds | `docs/sources/outlier_integrity_v2/manifests/`, `.../FROZEN_THRESHOLDS.json`, `docs/sources/outlier_integrity_v21/HELDOUT_RULE.json`, `.../manifests/POPULATIONS.json` |
| Evidence reports and result data (V2: root cause, evaluation A-D boards, DLF readiness, R constraints, dev gates, historical replay incl. the one held-out run; V2.1: dev-stage exploratory evaluation and performance runs) | `docs/sources/outlier_integrity_v2/{rootcause,evaluation,dlf_readiness,r_constraints,gates_dev,replay}/`, `docs/sources/outlier_integrity_v21/{dev,perf_dev}/` |
| Owner report with independent reviewer findings (section G) and the registered criteria scorecard | `docs/sources/outlier_integrity_v2/OWNER_REPORT.md` |
| Known deviations and implementation clarifications | `docs/sources/outlier_integrity_v2/DEVIATIONS.md`, `docs/sources/outlier_integrity_v21/DEVIATIONS.md` |
| Reproduction scripts that live beside their evidence (`*.py`, `*.sh`, `build_*.py`, `run_all.sh`) | under the directories above |

The reproduction scripts are evidence, not part of the product. Nothing under `src/`, `scripts/` or the
test tree imports them, and several need code that exists only on the #1884 branch.

## What the records say (pointer, not restatement)

* V2 registered verdict: **MORE RESEARCH REQUIRED** (`OWNER_REPORT.md`, section H). V2's held-out
  boards are **spent**.
* V2.1 dev stage (`outlier_integrity_v21/dev/README.md`): exploratory only, **not** a gate of record,
  **NOT READY** for the Stage 2 freeze as registered. The identity prerequisites (U2, U2b, U3, VID) are
  recorded as BLOCKED until merged and live in the automated refresh before **2026-11-04T00:00Z**.
* Standing holds, unchanged by anything here: `outlier_integrity_v2` and every sub-flag default OFF,
  the DLF IDP hold ON, DLF Rookie IDP held, D4 OFF, freshness v2 OFF. Activation of each is
  owner-reserved.

## Open owner questions (as recorded in the extracted files)

* **O-2** (preregistration section 12): whether the wrong-player gate uses AD2-ID (swaps carry the
  swapped player's own published identity fields) instead of AD2 as registered. Default: AD2 as
  registered. It counts only if recorded in the repository before the V2.1 Stage 4 run commit and blind
  to held-out results. Intake id `IV21-O2` is in the #1884 copy of `docs/OWNER_REQUESTED_TODO.md`,
  which this change does not touch.
* The activation decisions listed above.

## Reconstructed wording (read before quoting the owner)

`OUTLIER_V21_O1_DECISION_2026-10-20.md` describes itself as the owner's answer "verbatim". It is a
**transcription made inside the authoring session** of an answer given through an interactive
multiple-choice prompt (`AskUserQuestion`), not a copy of a file the owner wrote. The extractor has no
independent copy of the owner's original and cannot confirm the transcription. Treat the following as
**reconstructed** until the coordinator or the owner confirms them against the original conversation:

* the exact wording of the selected option for O-1 ("Real history, cold start safe (Recommended)") and
  its explanation text;
* the appendix "complete answer file", which also reproduces unrelated Trade Advisor fairness choices
  (OD-F1, OD-F2, OD-F3/F5) that belong to a different lane.

The decision's substance (O-1 gate of record = real prior history, cold-start safe, wrong-player and
wrong-scale gates must still pass) is also what the V2.1 preregistration encodes in its sections 7 and
11, so the two records agree; agreement between two records written by the same session is not
independent confirmation.

## What is deliberately not here

| Left out | Why |
|---|---|
| `src/`, `scripts/oiv2*`, `config/sources/outlier_integrity_v2.json`, `tests/**/*oiv2*`, frontend label changes, `server.py` and `data_contract.py` hooks | Experimental detection code; stays on #1884 until the owner decides. |
| `docs/OWNER_REQUESTED_TODO.md`, `docs/EXECUTION_PLAN.md`, `docs/WORK_CLAIMS.md`, `README.md`, `docs/ARCHITECTURE.md` edits from #1884 | Coordinator-owned or flag-count bookkeeping tied to the detection flags. |
| Scraper and identity-capture prerequisites (U2, U2b, U3, VID) | Separate code PR, because they carry a deadline the documentation does not. |
| `tests/fixtures/oiv2/**` | Inputs to the detection tests. |

Several extracted documents cite paths (`src/api/source_integrity.py`, `src/robust_filter_shadow/oiv2_*.py`,
`config/sources/outlier_integrity_v2.json`, ...) that exist only on the #1884 branch. Those references
are accurate for that branch and are intentionally left as written.

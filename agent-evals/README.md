# agent-evals

Repo-specific agent/harness evaluation foundation, per Priority 8 of
`docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md` and
`docs/engineering/AGENT_HARNESS_EXTERNAL_GUIDANCE_RECONCILIATION_2026-09-12.md` Part E.

This directory evaluates **model + harness together** on real repository tasks, not
model reputation in the abstract. It exists because this repository's Agent OS,
skills, and provider adapters change over time, and material changes to them should
be checked against real behaviors before becoming canonical
(`docs/AGENT_OPERATING_SYSTEM.md` §14: "Material Agent OS/skill/model-routing changes
should eventually be evaluated against this suite before becoming canonical").

## What this is not

- **Not a second Agent OS or a second memory system.** It only *consumes* the
  existing `docs/AGENT_OPERATING_SYSTEM.md` contracts and
  `config/steward/contracts.schema.json`'s vocabulary (status enum, evidence shape).
- **Not a live model-execution harness.** Nothing here dispatches a model or makes a
  network call. Grading is 100% deterministic Python over a JSON file you provide.
- **Not authorization for recurring paid inference.** Capturing a real agent run
  against a case is a manual, interactive, budgeted step a person performs
  separately — never something CI does automatically. See "Capturing a real run"
  below.
- **Not activation of anything in `docs/AGENT_OPERATING_SYSTEM.md` §6** (the
  autonomous-loop safety envelope). Evaluation is not activation, and a harness
  change proving out well here still needs the same human/integration approval any
  other harness change needs.

## Layout

```
agent-evals/
  README.md                          this file
  schema/
    case.schema.json                 shape of one eval case
    run_artifact.schema.json         shape of one captured/graded run
  cases/
    *.json                           the eval corpus (see below)
  graders/
    deterministic.py                 the grader (no deps, no network, no model calls)
  run_eval.py                        CLI: --list, --case <id> --artifact <path>
tests/agent_evals/
  test_case_schema.py                every shipped case validates and is internally consistent
  test_deterministic_grader.py       the grader actually discriminates pass from fail
```

## The eval corpus

Every case is grounded in a real, already-documented repository incident or
invariant — named in the case's `based_on` field — not invented busywork. The
corpus currently has one case per named behavior from the reconciliation directive
plus a dedicated classic "missing→zero" case (Priority 8's own first candidate task):

| category | case |
|---|---|
| `missing_never_zero` | `missing-never-zero-ros-playoff-odds` |
| `write_ownership` | `coercion-baseline-regenerate-not-hand-edit`, `duplicate-canonical-owner-rejection` |
| `stale_evidence_rejection` | `benign-automation-move-classification` |
| `skill_selection` | `trivial-doc-fix-does-not-load-unrelated-skill` |
| `owner_question_autonomy` | `methodology-invention-refusal-w1-27-rate-model` |
| `finish_line_persistence` | `merged-is-not-verified` |
| `reviewer_independence` | `reviewer-rejects-unverified-test-claim` |
| `proportional_verification` | `proportional-verification-trivial-vs-canonical-change` |
| `delegation_discipline` | `no-spawn-without-independent-work` |
| `graph_failure_containment` | `sibling-work-survives-failed-unit` |
| `external_guidance_hygiene` | `unsupported-adoption-statistic-rejected` |
| `cross_session_continuity` | `cross-session-recovers-durable-state` |

Run `python agent-evals/run_eval.py --list` for the live list (source of truth over
this table if they ever drift).

## Grading model

A case's `grading` block names a small set of deterministic checks:

- `allowed_final_statuses` — the artifact's declared `status` must be one of these.
- `required_strings` / `forbidden_strings` — substring checks against the artifact's
  self-reported `summary` text.
- `require_unresolved_nonempty` — the artifact's `unresolved` field must name real
  outstanding items, not be empty or the literal string `"NONE"`.
- `allowed_path_globs` / `forbidden_path_globs` — every entry in `changed_files` must
  (or must not) match the given glob patterns.
- `required_flags` — a case can require a self-reported boolean flag to be `true` or
  `false`/absent (e.g. `claimed_verified_without_production_evidence: false`).

## What this does and does not prove

**This grades the DECLARED state of a run artifact, not ground truth.** The grader
cannot independently verify that a flag like `regression_test_added: true` is
actually true — it can only check that the artifact author declared it. This is the
same posture `config/steward/contracts.schema.json`'s checkpoint verification
already states: *"These are evidence-recording guards, not a substitute for
independent verification of the referenced artifacts."*

A passing grade is therefore **necessary evidence for a harness comparison**
("did this run at least claim the right things"), not **sufficient proof** that the
underlying work was correct. Closing that gap — confirming a flagged claim against
the actual transcript/diff — is a separate, human or independent-reviewer step,
consistent with `docs/AGENT_OPERATING_SYSTEM.md` §4's "Independent reviewer" role.

## Capturing a real run

1. Pick a case: `python agent-evals/run_eval.py --list`.
2. Give the case's `objective` (and `setup`, if present) to an actual interactive
   agent session as its task.
3. From the session's actual outcome, write a `run_artifact.schema.json`-shaped JSON
   file by hand: `schema_version`, `case_id`, `status`, `summary` (the agent's own
   final report text), `unresolved`, `changed_files` (what it actually touched), and
   any `flags` you can honestly attest to from watching the run.
4. Grade it: `python agent-evals/run_eval.py --case <id> --artifact <path>`.

This is deliberately manual and budgeted by a person each time — never wired into
ordinary CI, and never an unattended loop.

## Adding a case

1. Pick the `category` this case exercises from the enum in `schema/case.schema.json`.
2. Ground it in something real: a `based_on` pointer to a doc section, PR/issue
   number, or file+symbol. Do not invent a synthetic scenario with no repository
   analogue.
3. Write the JSON file under `cases/`, id matching the filename.
4. Run `python -m pytest tests/agent_evals -q` — `test_case_schema.py` will catch
   structural mistakes immediately.

## Comparing a harness change against a baseline

1. Capture a run of the relevant case(s) on the harness *before* the change.
2. Make the change.
3. Capture a run of the same case(s) *after* the change.
4. Grade both artifacts and compare pass/fail plus which specific `failures` changed.
   A harness change that flips a previously-passing case to failing is a regression,
   independent of whatever it was trying to improve.

This is the "deterministic grading -> model/harness comparison" stage of the
Agent-improvement flywheel in
`docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`'s "Useful
compound systems" section. It does not by itself promote anything — promotion of a
harness change still goes through ordinary review and integration, exactly as any
other repository change does.

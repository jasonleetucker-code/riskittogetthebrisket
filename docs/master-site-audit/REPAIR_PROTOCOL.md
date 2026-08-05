# Repair Protocol — read before changing any production code

The audit is finished and its findings are in `findings.json`. This file is the
contract for repairing them. It exists because a repair that cannot be shown to
have worked is indistinguishable from one that did not happen.

## The standard, in one line

**Every fix ships with a test that FAILS against the pre-fix code**, and you must
have watched it fail.

That is not a formality. Two examples from this effort:

- The whole 1,754-test frontend suite passed with the TEP defect in place. A test
  written after the fix, without checking it goes red first, would have proved
  nothing.
- `frontend/__tests__/draft-logic.test.js` contained a test *pinning the draft
  bug as the contract* — named "capped at DEFAULT_INITIAL_SLOTS", asserting 8
  picks produce 6 slots. A test that encodes a bug turns every correct fix into a
  failing build.

To check: `git stash push -q <the source file>`, run the test, confirm red,
`git stash pop -q`. Record the red count in the commit message.

## Non-negotiables

1. **Read the finding first**, in `findings.json` — its `observed`,
   `reproduction`, and `verification.reasoning` if it was adversarially reviewed.
   45 findings were re-checked by an independent refuter and **31 were rescoped**;
   the `priority` field is the VERIFIED one and `authoredPriority` is what the
   original workstream claimed. Repair what was verified, not what was authored.
2. **Fix the root cause, not the one symptom the finding names.** The FAAB defect
   was reported against `positionBids`; the same unnormalized pooling sat in four
   sibling aggregates. Fixing one would have left the identical bug next door.
3. **Reuse what is already in the tree.** The correct answer is usually present
   and simply not reached — `luck.py:193` already passed `s.season` correctly,
   `resolvePickRow` already applied `pickAliases`, `gameplan.py` already returned
   `owner_not_in_simulation`. Prefer the existing helper over a new one.
4. **Never invent a number to replace a missing one.** Absence must stay
   representable: return `None`, stamp a reason, and let the surface abstain. The
   platform's characteristic defect is missing data resolving to a confident
   value — do not add another instance while fixing one.
5. **Do not edit source while a test suite is running.** `inspect.getsource`
   reads the file at call time, so a mid-run edit produces phantom failures in
   unrelated tests.

   **This has now produced three false alarms**, and the orchestrator caused all
   three by running the full suite while a repair wave was editing source. The
   signature is always the same: a handful of failures in modules nobody touched
   (`tests/intel/test_defect_fixes.py` and one `te_premium` invariant are the
   usual victims), all of which pass in isolation and together. Timestamps
   settle it — compare the run's finish time against `git log --format=%cI`.

   **The rule that follows: the full-suite gate only runs on a QUIESCENT tree.**
   No wave in flight, nothing being edited. A per-area suite is fine to run
   concurrently; the full gate is not, and a green full gate measured during a
   wave means nothing either.
6. **One root cause per commit**, so it stays bisectable. Say `Closes W##-F###`
   in the body — `tools/verify_closure.py` parses it sentence-scoped, so
   mentioning a finding you did NOT fix in the same sentence will over-claim.

## Verifying

- Run the suite for every area you touched, and the full suite before the phase
  ends — on a quiescent tree, per rule 5. Baseline to beat: **6,553 passed /
  0 failed** (Python, measured after wave C), **1,866 passed / 0 failed**
  (frontend). The Python count grows as repairs add regression tests; it started
  at 6,278.
- Where the finding has a measurable before/after, MEASURE IT and put both
  numbers in the commit message. Precedents: 627/654/135 rank/tier/value
  divergences → 0/0/0; 48.0s → 0.57s; 32-of-35 TEs SELL → 14-of-35.
- The stack is running (API `:8000`, pages `:3000`). See `EVIDENCE_LOG.md` for
  the bring-up, and note the topology rule in `AUDIT_PROTOCOL.md`: a browser
  pointed straight at `:3000` produces 404s production never sees, so page
  observations need Playwright request interception.

## Scope discipline

- Production behavior changes only where a finding justifies it. If you discover
  something real that no finding covers, add a finding rather than silently
  widening the diff.
- If a finding turns out to be wrong, say so and leave the code alone. A
  reasoned refusal with evidence is a better outcome than a change that makes a
  correct system worse — one audit finding was already overturned this way.
- If a repair is blocked by absent data (`data/bdvm/`, `data/intel/`, no sharp
  ledger), stop and report it as blocked, naming the exact missing artifact. Do
  not fabricate a fixture that makes the code look exercised.

## Status

`tools/verify_closure.py` tracks what is closed. It distinguishes a commit
*claiming* a fix from a reproduction that no longer reproduces, and it refuses to
blind-execute reproductions that POST or write — those are reported as
needing manual verification rather than skipped.

# AI-agent ecosystem implementation campaign

**Status:** INTEGRATION CANDIDATE — production verification is pending.
**Owner directive:** 2026-10-03 implementation request; research issue #1628 and research PR #1629.
**Agent-OS-Receipt:** `cdca1dca8385f70c0989302dece8d1bd4ce4843c`.

This is the campaign's dependency and evidence map, not a second product or
implementation authority. `docs/EXECUTION_PLAN.md` remains the canonical
repository authorization ledger. The owner's new directive authorizes the
bounded engineering capabilities below through normal claims, review, CI,
integration, deploy and production proof. It does not authorize paid services,
methodology promotion, source activation, autonomous merge/deploy, or broader
production permissions.

## Campaign-start reconciliation

- Initial base inspected: `f595c5a0bb106554e96cc7b26b53d1312f05a7dd`.
- Week 1 completion contract: 30/30 literal `VERIFIED` at session start.
- Research PR #1629 was incorporated into the integration candidate; its
  findings remain candidate evidence, while live files and claims decide work.
- PR #1627 merged on 2026-10-04; PR #1513 still changes
  `docs/OWNER_REQUESTED_TODO.md` and `docs/EXECUTION_PLAN.md`. The compact
  owner-intake pointer and execution-plan section remain queued behind #1513.
  Their absence here is **partial authority capture**, not a claim of completion.
- Open Dependabot PRs #1506 and #1508 change `requirements.txt`; their exact
  dependency changes must regenerate the locks before either can integrate.

## Dependency order and ownership

| Unit | Canonical owner to extend | State | Required proof |
|---|---|---|---|
| Exact Python dependency lock | `requirements.txt`, `requirements-dev.txt` | IMPLEMENTED ON TRAIN — hash-locked CI/scheduled refresh and Linux wheelhouse proof; production parity pending | Exact-head train CI, deploy and served dependency digest |
| Tested artifact and production identity | `deploy/`, `.github/workflows/deploy.yml`, `src/api/build_identity.py` | IMPLEMENTED ON TRAIN — release manifest v2 binds CI frontend and backend wheel tar; saved v2 rollback uses offline wheels and frontend bytes; production proof pending | Final train CI, strict candidate, deploy, served fingerprint, rollback |
| Typed API pilot and frontend parity | `server.py`, `src/api/`, existing frontend client | IMPLEMENTED ON TRAIN — `/api/leagues` schema, OpenAPI generation and deterministic frontend parity; production pending | Final contract/E2E CI and served route |
| Application trace and SLOs | Existing API/log/performance owners | PARTIAL — correlated route trace and privacy-safe source lifecycle proof implemented; production source dispatch and end-to-end served trace pending | Trace, source and SLO evidence from merged revision |
| Steward spans, eval bridge, routing scorecards | `src/steward/`, `agent-evals/` | IMPLEMENTED ON TRAIN — execution receipts, deterministic adapter, scorecards and challenger-only routing; no automatic promotion | Final eval/CI and live run evidence |
| Optional typed decision advisor | Existing Steward router/evals | SHADOW ONLY — offline task-profile comparison; no provider, labeled corpus, calibration or active routing | Held-out labels and risk/coverage before any advisory promotion |
| Class-B executor and isolation | Existing Steward controller/contracts | PARTIAL — fixed deterministic repair and one SHA-pinned local-model evidence task passed credential-free Docker/host verification; main-only publisher still unexercised | Final train isolation/model CI; post-merge branch and review PR; broader authority remains inactive |
| Action receipt integrity | Existing Steward store/controller | IMPLEMENTED ON TRAIN — SQLite/JSONL mirror recovery, conflict and truncation refusal; no independent cryptographic anchor | Final exact-head tests and persisted receipt proof |
| Browser exploration and eval corpus | Existing Playwright and `agent-evals/` | PARTIAL — public desktop/mobile exploration, 44 deterministic production E2E checks, structured journey evidence and adversarial cases; campaign production proof pending | Final train E2E and post-deploy journey |
| Final reconciliation | Canonical docs, CI, deploy and production evidence | IN PROGRESS — train #1667 incorporates product #1658, current relevant main movement and reviewed component heads; final gates and deployment pending | Exact merged and served identity; unresolved debt |

No new generic orchestration framework, vector memory, generic feature store,
MCP conversion, paid collector/sandbox, or self-promoting routing is planned.
Domain methodology and production permissions remain with their current owners.

The integration train #1667 contains fixed Class-B pilot #1665, source
lifecycle proof #1666, backend wheelhouse/cutover #1669–#1670, and the bounded
model task #1671. The deterministic pilot repaired one broken link. The model
task used a pinned free local model to classify an audited successful pilot
run in a credential-free, network-denied container; an independent verifier
accepted only one exact document proposal. Neither grants general Class-B
coding authority. Only after merge can the separate trusted publisher exercise
its review-branch/PR path; its GitHub token is broader than branch-only under
the current main ruleset. The source proof parses private scrape events on the
production host and emits an allowlisted summary; its current production
dispatch remains pending. Saved artifact deploy and rollback also require L3.

An agent-declared 2026-10-04 read-only Playwright CLI spot check opened production `/league`
at desktop and 390×844 mobile widths. The Home data rendered, and selecting
Trades on mobile reached `/league?tab=activity` with a populated Trade activity
panel. The browser logged a `favicon.ico` 404 and a CSS preload warning. This
single visit has no retained CI artifact and is not a regression suite or proof for the unmerged campaign; the
existing production E2E workflow and deterministic journey assertions remain
the browser acceptance path. The full Trades accessibility snapshot was large,
reinforcing the need for targeted browser queries and bounded evidence summaries.
The existing `public-league.spec.js` was then run read-only against
`https://chaseupside.com` in desktop Chromium and 390×844 mobile Chromium:
44 passed, zero skipped (local runner, 2026-10-04). The retained local HTML
report is in the ignored `tests/e2e/playwright-report/` directory; the result
is agent-declared rather than CI-attested. The scheduled production E2E run
[37160601511](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/37160601511)
also succeeded on main commit `0aaff7cdb2842dd4a40f4278523dbdd20f32cfc2`
before this check. Neither run exercises unmerged campaign code.

The browser-evidence unit adds an opt-in, bounded JSON reporter to the same
Playwright run, preserving the existing failure guards and deterministic
assertions. It records each selected journey's project, outcome, retries,
duration and failure-artifact presence without raw error text, page content or
attachment paths. A local read-only production run on 2026-10-04 selected the
public `/league?tab=awards` deep-link assertion in desktop and 390×844 mobile
Chromium: the generated `tests/e2e/playwright-report/journey-evidence.json`
reported 2 passed, 0 failed/flaky/skipped, one attempt per test, and no failure
artifacts. This local report has `source_commit: null` because the working tree
was uncommitted, and it is ignored by Git. It is agent-declared evidence for
the reporter and current production journey, not CI-attested proof of unmerged
campaign code. The first CI run for the reporter
([37172182324](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/37172182324))
uploaded 330 results (265 passed, 65 skipped, zero failed or flaky). Review of
that artifact found the single `target_origin` field ambiguous in CI, where
API requests use port 8000 and page navigation uses port 3000. The latest head
records separate `api_origin` and `page_origin`; new exact-head CI is required.
The earlier CLI spot check is also agent-declared.

## Engineering applicability

For the dependency unit: reproducible artifacts and supply-chain control are
`APPLY_NOW`; existing manifest and npm lock are `ALREADY_COVERED` foundations.
Typed API, tracing, evals and capability isolation are separate authorized units,
not implied changes to this lock PR. Product valuation, ranking, DFS and source
methodology changes are `NOT_RELEVANT` to the lock implementation.

## Current release gate

- The final train head needs full L2 validation, E2E, isolation, model and
  wheelhouse proofs, plus strict release-candidate validation against the
  current `main` tree. Relevant automated `main` movement is reconciled once
  before the frozen gate; no prior head's green check substitutes for this.
- After merge, production deploy must compare the intended Git SHA, frontend
  artifact ID and backend wheelhouse digest with `/api/status`, and exercise
  health, critical routes, source lifecycle proof and browser useful states.
- The main-only bounded-model dispatch must create a real review branch and
  draft PR; that generated PR needs independent validation. The general
  Class-B lane remains inactive.
- Owner intake and the execution-plan pointer remain queued behind #1513's
  active shared-file claim. They are partial authority capture, not complete.

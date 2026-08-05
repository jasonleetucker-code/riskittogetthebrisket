# Master Site Audit — Risk It To Get The Brisket

Evidence-backed implementation, accuracy and completion audit of the whole platform.
**Audited commit `e96c06ef`, 2026-08-04/05. Nothing was repaired.**

## The verdict in ten lines

The engine is better than its reputation; the screen is worse than the engine. The blend spine is
deterministic and monotonic, the test suite genuinely runs green (6,278 Python + 1,754 frontend
tests, executed here rather than taken on trust), and the production build passes its own bundle
budgets. But the board `/rankings` renders is **not** the board `GET /api/data` serves — every
page load silently posts a TE-premium override that bypasses the backend's own measured curve,
changing 627 of 740 ranks. A separate one-line type error makes every rest-of-season number a
replay of the 2024 season and tells the best roster in the league to sell.

**431 findings published, 9 P0, 86 P1.** The nine P0s reduce to five root causes, and two diffs —
sizes S and XS — close six of them.

## Start here

| Question | Document |
|---|---|
| What did you find, and can I trust the site? | **[EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md)** |
| Can I trust subsystem X specifically? | [TRUST_RATINGS.md](TRUST_RATINGS.md) — all 24 named subsystems |
| What should I fix, in what order? | [REPAIR_ROADMAP.md](REPAIR_ROADMAP.md) |
| What do I do first? | [FIRST_REPAIR_PROMPT.md](FIRST_REPAIR_PROMPT.md) — copy-paste |
| Show me the full finding list | [FEATURE_STATUS_MATRIX.md](FEATURE_STATUS_MATRIX.md) · [`findings.json`](findings.json) |

## The rest

| Document | Contents |
|---|---|
| [PROOF_CASES.md](PROOF_CASES.md) | The 24 mandated source-to-screen traces with real numbers |
| [EVIDENCE_LOG.md](EVIDENCE_LOG.md) | Every measurement, its command, and what could not be measured |
| [VALUE_FLOW_MAP.md](VALUE_FLOW_MAP.md) | Where every player value is computed, read, cached and displayed |
| [FORMULA_INVENTORY.md](FORMULA_INVENTORY.md) | Every formula, and where the same concept uses different math |
| [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md) | Runtime architecture and the request path |
| [ROUTE_API_JOB_INVENTORY.md](ROUTE_API_JOB_INVENTORY.md) | 100 routes, 41 pages, 22 workflows, 20 timers, 89 scripts |
| [DATA_SOURCE_AUDIT.md](DATA_SOURCE_AUDIT.md) | Source status, coverage, freshness, failure behaviour |
| [HISTORICAL_DATA_GAPS.md](HISTORICAL_DATA_GAPS.md) | What history exists, what must be labelled unofficial |
| [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md) | Per-route and per-page measurements, caching |
| [SECURITY_AUDIT.md](SECURITY_AUDIT.md) | Exposure sweep and the public/private boundary |
| [TEST_GAP_MATRIX.md](TEST_GAP_MATRIX.md) | What a green suite of 6,278 tests does and does not prove |
| [CONFLICT_LOG.md](CONFLICT_LOG.md) | Docs vs code, doc vs doc, and audit-internal disagreements |
| [PRIOR_AUDIT_RECONCILIATION.md](PRIOR_AUDIT_RECONCILIATION.md) | The 531 prior findings, and the two contradictory verdicts |
| [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md) | The method every workstream followed |

`evidence/` holds 400+ raw artifacts — captured payloads, reproduction scripts, CSVs and
screenshots — plus the 31 per-workstream finding shards and the 45 verification verdicts.

## How to trust this audit

Three things were done differently from the audits already in this repository, and each is
checkable:

**It ran the software.** Every prior audit here is static analysis; the most recent one names its
own gap as *"no running server, no `pytest`, no live API responses."* This one booted the backend
and frontend from the repo's own seed path with the scraper monkeypatched off, probed all 100
route operations and all 41 pages, and ran both test suites. `EVIDENCE_LOG.md` has the commands.

**Findings had to survive an attempt to kill them.** The 45 highest-impact findings went to
independent refuters instructed to default to refuted. Result: **13 upheld, 31 rescoped, 1
overturned** — and every severity correction moved *downward*. Published priorities are the
verified ones; `authoredPriority` preserves what was originally claimed. Unverified audit
severities in this codebase run hot, which is worth remembering when reading the earlier audits.

**It corrected itself twice, in public.** The first browser capture ran without nginx and produced
222 console errors that were pure topology artifacts; those captures are retained as
`*-INVALID.json` and their symptoms pre-declared as non-findings so no workstream could report
them. And the executive summary originally grouped the TE SELL-label defect under the TEP
override — a workstream tested that claim instead of inheriting it and disproved it. Both
corrections are recorded rather than quietly edited away.

One finding was overturned outright and it publishes with the argument that killed it, because
deleting refuted work is how documentation drifts in the first place — which is the failure mode
this audit reports 25 instances of.

## Regenerating

```bash
.venv/bin/python docs/master-site-audit/tools/merge_registry.py   # shards + verdicts -> findings.json
.venv/bin/python docs/master-site-audit/tools/build_matrix.py     # findings.json -> matrix + rollups
```

Both are deterministic with no model in the loop, so the published tables cannot drift from the
registry they summarise. `merge_registry.py --strict` fails if any finding lacks a re-runnable
reproduction, claims `Implemented and verified` without a passing proof, or rates P0 without
naming the page a user acts on.

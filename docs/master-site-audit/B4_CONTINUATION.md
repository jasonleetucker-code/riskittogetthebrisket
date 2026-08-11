# B4 continuation — everything a fresh session needs

**Why this file exists.** B4 (W30-F023, percentile tail saturation) is
mid-flight. The measurement stage is done, committed and reproducible from
a pinned SHA; the repair stage is not started. A fresh session should be
able to pick this up from a one-line prompt, and this is the one place that
makes that true.

Read this, then `docs/ARCHITECTURE_HANDOFF.md` for the standing
architecture rules.

---

## 1. Where things stand

| | |
|---|---|
| Branch | `claude/dynasty-audit-consolidation-e75vdy` |
| Base | integrated `main` `a89a07ea3` (B3 merged as PR #793) |
| Open PR | **#798** — the active B4 pass, plus B3 residual tracking |
| Phase | Phase A closed; **B1/B1.2 (#776), B2 (#787), B3 (#793) all merged**. B4 authorized and **at the measurement checkpoint** |
| Production changed by B4 so far | **nothing** |

Merged phase outcomes, so they are not re-litigated:

* **B1 / B1.2** — percentile-coordinate repair merged; a Hill challenger
  was measured and **not promoted**. Champion is registry **v2**.
* **B2** — W02-F001 fixed: the Hill master is chosen from the rank's
  *coordinate pool* (`src/canonical/rank_coordinates.py`), never from the
  source's registry declaration.
* **B3** — W02-F003 fixed: the IDP corridor's hard `0.15` band cap removed,
  so the board-derived per-bucket P90 decides again. Three residuals stay
  open with one identity each side: `W02-F015`/**#794**,
  `W02-F016`/**#795**, `W02-F017`/**#796**. W30-F023 is **#797**.

## 2. What B4 is

`PERCENTILE_REFERENCE_N = 500`, but the board publishes ranks to
`OVERALL_RANK_LIMIT = 800` and sources rank deeper still. `p` saturates at
1.0, so distinct served ranks past 500 collapse onto one contribution.

**Treat it as a tail-policy defect, not a Hill refit.** Preserve the curve
through the region it was fitted to represent; let legitimately distinct
served ranks beyond the saturation point keep distinct values under an
evidence-supported policy.

**Do not start by changing N.** B1.2 proved rank-space behaviour depends on
`M = c·(N−1)`, so reference N is a coordinate *unit*: changing N while
leaving `c` alone changes the curve rather than repairing the tail. The
distinction B4 must hold is **coordinate definition** vs **tail policy**.

## 3. Done and committed

Evidence lives in `docs/master-site-audit/evidence/W30/`:

| file | what |
|---|---|
| `b4_tail_measure.py` | pin + reproduction harness (`--pin`, `--reproduce`) |
| `b4_tail_report.json` | machine-readable pin, path mix, totals |
| `b4_tail_reproduction.txt` | verbatim run output |
| `B4_TAIL_TRACE.md` | §5 trace — every saturation point and tail assumption |
| `B4_TAIL_CORRECTION.md` | the path-gating correction, with the withdrawn claim |

**The pin.** Board `exports/latest/dynasty_data_2026-08-11.json`
sha256 `8fb6ede274171aee…` (834,861 B, scraped 11:32:57Z, 1,074 players),
24 source CSVs hashed, champion registry v2, `PERCENTILE_REFERENCE_N` 500,
`OVERALL_RANK_LIMIT` 800, all source depths recorded. `dirtyPaths` is
enumerated and classified rather than a bare bool — a run rewrites its own
outputs, so the flag was self-referential.

**Reproduction, path-gated.** 421 of 5,146 rank-Hill observations sit past
rank 500 (**8.2%**), touching **254 of 1,092** board rows. Separately, 282
value-direct observations carry a deep rank and are *not* part of this
defect.

| source | past N | ranks collapsed | deepest Hill rank | clamped → continuous |
|---|---|---|---|---|
| `draftSharksIdp` | 193 | 193 | 730 | 1698 → 1345 (+26%) |
| `idpShow` | 170 | 170 | 877 | 1698 → 1197 (+42%) |
| `dlfIdp` | 23 | 19 | 620 | 1698 → 1489 (+14%) |
| `draftSharks` | 18 | 18 | 684 | 1698 → 1400 (+21%) |
| `dlfRookieIdp` | 8 | 6 | 661 | 1698 → 1431 (+19%) |
| `flockFantasySfRookies` | 6 | 6 | 621 | 794 → 635 (+25%) |
| `fantasyProsIdp` | 3 | 3 | 572 | 1698 → 1564 (+9%) |

Position blast radius: DL/EDGE 66.9%, DB 62.6%, LB 43.0%, TE 14.5%,
QB 5.7%, RB 1.4%, WR 1.4%, **picks 0.0%**.

**Three findings the original W30-F023 entry did not have:**

1. **There are FOUR clamps, not two** — `rank_to_percentile:170`,
   `percentile_to_value:484`, the standalone `hill()` in
   `model_registry/holdout.py:168` that **scores challengers**, and `_hill`
   in `scripts/fit_hill_curve_percentile.py:261`. Missing the last two is
   worse than a partial fix: a repaired board would be scored by a
   still-saturated evaluator and any refit would re-learn the saturated
   shape. **There is no one-line repair** — the policy needs one canonical
   owner all four defer to, or serving, fitting and scoring disagree about
   where the tail is (the W30-F008 defect class).
2. **The frontend already disagrees with the backend past rank 500.**
   `HillCurveExplorer.jsx:35-42` re-evaluates the Hill in rank form with
   *no* `p ≤ 1` clamp, so the drawn curve and its own scatter diverge past
   500 by construction, live today.
3. **Nine test files pin the collapse as intentional** — including
   `tests/canonical/test_coordinate_equivalence.py:155-179`, written during
   B1.2. Each must be re-decided deliberately, not "fixed up".

**The boundary answer for candidate C**: the deepest rank-Hill rank
consumed by a *served* row is **877**, past `OVERALL_RANK_LIMIT` 800. So a
policy saturating at the board limit would still collapse genuine evidence.
Four domains to keep separate: board limit 800, deepest served canonical
rank 740, saturation point 500, deepest translated effective rank 899,
deepest rank-Hill rank 877.

## 4. Not done — the rest of B4, in order

1. **RED tests** on the real canonical functions (never a copied formula).
   Minimum: rank 500 vs 501 collapsing; 500 vs 800 collapsing; multiple
   distinct deep IDP ranks collapsing to one contribution; **the second
   clamp undoing a partial first-clamp repair**; ranks 1–500 unchanged by a
   pure tail-policy repair. Plus a regression for the **fallback** case — a
   value-based source whose raw value is missing/out-of-range/suppressed
   takes the Hill path and must get the correct tail policy. That path has
   **zero live traffic on this pin**, so it needs a test, not an
   observation.
2. **Declare evaluation criteria before choosing** (B4 §8 lists them).
3. **Measure candidates A–D** on the identical pin: A current saturation,
   B continuous extrapolation through the served range, C explicit
   served-range saturation via a *transformed coordinate* (must be shown
   algebraically not to be a refit), D any other evidence-supported policy.
4. **Minimum root-cause repair if the evidence supports one**, then GREEN.
5. **Rebuild and compare the board** — values changed, rank movement
   distribution, membership at the served cutoff, composition at top
   50/100/200/400, positional effects, largest movers, pick movement via
   the relative rookie stages, and any upward movement despite lower raw
   contributions (B1.2 saw this; it must be explained, not dismissed).
6. **Measure the B3 corridor interaction** — clamps before/after, bucket
   distribution, anchor source, direction — **without reopening B3**. If a
   tail change exposes a new corridor defect, record and stop.
7. **Full gates + exact-HEAD CI**, re-run if a docs-only commit moves HEAD.
8. Update W30-F023 without overwriting B1.2's historical evidence. Final
   recommendation exactly one of `W30-F023 VERIFIED FIXED — READY FOR OWNER
   REVIEW` / `MORE B4 EVIDENCE REQUIRED` / `BLOCKED BY A CANONICAL
   DEPENDENCY`, plus an explicit statement of whether the chosen policy is
   continuous through the served range, bounded at a justified boundary,
   unchanged, or another measured policy. **Then STOP** — no B5, no CE, no
   owner hotfixes.

## 5. Constraints that stay in force

* **No `promote`, no `apply`, no Hill champion constant change**, no
  `.068`, no refit of GLOBAL/OFFENSE/IDP/ROOKIE to compensate for the tail,
  no source-weight change, no adaptive weighting, no KTC/IDPTC semantics
  change. A tail defect must not be fixed by changing the fitted head.
* **Keep separate unless B4 proves a hard dependency**: #794 corridor
  anchor/voter circularity, #795 systemic-drift self-widening, #796
  confidence-bucket validation, C17's OFFENSE half, the IDP master's
  historical 1.552× fit-scale claim. If W30-F023 proves inseparable from
  one, **stop and report** rather than broadening scope.
* **Missing is never zero.** A source that stops before a rank has no
  opinion about the players below it — do not synthesise deep-tail
  observations to fill a new continuous range. Distinguish genuine rank,
  no coverage, source cutoff, translated rank, fallback coordinate.
* **Performance**: a tail repair is pure arithmetic. No new fetches, no
  per-player network work, no request-time rebuilds.
* Every candidate comparison uses **identical pinned B4 inputs**. Prior
  phases' numbers stay attached to their own pins — never silently
  recompute an old figure on new data and present it as the same
  experiment.
* Red before green; one root cause per commit; full suites only on a
  quiescent tree.

## 6. Reproducing the current state

```bash
git fetch origin && git checkout claude/dynasty-audit-consolidation-e75vdy
python -m venv .venv && ./scripts/setup.sh      # if the container is cold
.venv/bin/python docs/master-site-audit/evidence/W30/b4_tail_measure.py --reproduce
```

The clone must be **unshallowed** (`git fetch --unshallow`) or every
git-derived audit signal lies. The full Python gate is
`.venv/bin/python -m pytest tests/ -q -x -m "not livedata"` and takes
~23 minutes here; do not extrapolate a total from the early percentage.

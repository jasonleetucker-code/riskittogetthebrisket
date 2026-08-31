# V1-61 Production Consumer Proof — 2026-08-30

## Scope

This record captures fresh production evidence for `V1-61 | Sharp Roster Percentage` only. It does not change Sharp methodology, authentication, canonical ownership, identity/value/lineup semantics, missing-data semantics, or the V1 denominator.

## Implementation ancestry

The V1-61 performance sequence culminated in PR #1186, merged as:

`84041921b34e25b2aa8b978b3e6f3e70abb9fa6e`

A later Deploy Production guard run (`33326498288`, attempt 2) read the production deploy-state file and recorded production at:

`f0e887cf66a21aa0f2ed022fdba2c5f1ceba61c7`

GitHub ancestry proves `f0e887cf66a21aa0f2ed022fdba2c5f1ceba61c7` is exactly two commits ahead of #1186 and contains it. The two intervening commits are data/freshness refresh commits, not alternate Sharp product implementations.

The guard refused to redeploy #1186 because doing so would have moved production backward by those two already-shipped commits. This is evidence that #1186 was already contained in the live production tree, not a deploy failure of the product change.

## Real consumer proof

Fresh workflow:

- `V1 Authenticated Production Verification (ephemeral guest session)`
- run `33330872852`
- started 2026-08-30T19:26:26Z
- workflow head `3c713e17ffa4e76968d0698e15bfcca33043e531`
- API verification suite: exit 0
- job conclusion: success

The workflow minted a real ephemeral `guest_pass`, logged in through `/api/auth/login`, exercised the deployed API, and revoked the pass in the same run.

Dedicated V1-61 check:

`V61A | sharp roster-percentage transparency fields, null never zero`

Result: **PASS**.

Observed deployed response:

- `cohortCoveragePct = 0.7604`
- `cohortManagers = 2396`
- `eligibleRosters = 9529`

Verifier detail:

> transparency block present with typed coverage (cohortCoveragePct=0.7604, cohortManagers=2396, eligibleRosters=9529)

This is materially different from the prior repeated V1-61 evidence, where the same real consumer never returned before the 60-second client window and `V61A` ended `unmeasurable` with `TimeoutError: The read operation timed out`.

The consumer now returns a populated, typed, truthful roster-percentage response within the verifier window. Missing/null semantics were not converted to zero and authentication was not weakened.

## False-green checks

The evidence does **not** rely on any of the following:

- a merge being treated as verification;
- internal-only profiler timing being treated as consumer proof;
- raising the verifier timeout;
- a public auth bypass;
- partial results;
- manager/roster dropping;
- missing-to-zero coercion;
- a duplicate Sharp cohort/scoring owner;
- a stale pre-#1186 tree.

The existing ONE canonical Sharp path remains the consumer path exercised by `V61A`.

## Adjudication

The live completion contract currently records V1-61 as `IMPLEMENTED_UNVERIFIED` because the dedicated production-consumer verifier could not obtain a response. That named engineering blocker is now closed by run `33330872852` on a production tree proven to contain #1186.

This evidence supports reconciliation of V1-61 from `IMPLEMENTED_UNVERIFIED` to `VERIFIED` at its stated L4 level. Until `docs/VERSION_1_COMPLETION_CONTRACT.md` is reconciled and merged, the canonical denominator tally remains whatever that contract literally states; this proof does not silently edit the numerator.

---

## Amendment 2026-08-31 — a scoring regression this record did not cover, and the re-measurement that closed it

This section corrects two things about the record above. Neither invalidates its
latency finding; both change what it was safe to conclude from it.

### 1. The false-green list above is missing an axis, and that axis was not clean

The list does not ask whether **qualification or scoring changed** across the
five perf PRs. Asked afterwards, cumulatively, against the true pre-`#1183`
baseline `56a9be9` rather than pairwise between PRs, the answer was **yes**.

`#1183` threaded `sorted_population` into `_performance_component`, so the
championship shrinkage base became a `_mean` over the same multiset summed in a
different order — one ULP (7.2e-16) from `build_population`'s `observed_base`,
which is the value that fills `championshipRateShrunk`. A manager's recomputed
shrunk rate is looked up in that very population, and it holds only 44 distinct
values across 3,390 entries (largest tie block 150), so one ULP pushes each
manager off its own tie block and moves its percentile by up to 0.022.

Measured at a shuffled 12,000-manager population:

| field | rows changed |
|---|---|
| `components` | 3,390 of 3,390 evaluable managers (100%) |
| `score` | 3,230 (max delta 0.40) |
| `score_percentile` | 3,102 |
| **`qualified`** | **8 — sharp cohort membership** |

Repaired in `#1189` (merge `b6559ac`). The deployed tree is now byte-identical
to the pre-`#1183` baseline — `56a9be9` == `origin/main` `0b4514b` == deployed
`1f65765c`, whole `score_managers` output compared field by field with floats
rendered via `repr`, at N=3,000 / 12,000 / 45,000 — with the performance win
preserved (N=45,000: 138.99 s -> 1.11 s, 125x).

### 2. Run `33330872852` was measured on the board carrying that regression

Its numbers stand as latency evidence and nothing above is withdrawn. But
`cohortManagers=2396` / `eligibleRosters=9529` describe a board whose scoring
was moving, so they were not a safe basis for promotion.

The promoting evidence is therefore a **re-measurement on the repaired tree**:

- authenticated run `33347132201`, 2026-08-31T01:18:53Z — `V61A` **pass**,
  `cohortCoveragePct=0.7597`, `cohortManagers=2397`, `eligibleRosters=9493`
- Lane 4 on-box run `33348027841`, 2026-08-31T01:35:22Z — **stamps production's
  own git HEAD**, `deployed_sha: 1f65765c14e396443b5480f244af13a1fae2a867`,
  which the record above could only derive from deploy records
- profiled `build_board` wall **24,012.1 ms** (was 57,396.3 ms post-`#1185`),
  and `cohort_compute` fired for 11,518.6 ms of the 11,523.1 ms `cohort_members`
  total, so this is the **cold** path rather than a memo hit — which is what
  answers "cached result hiding a slow cold path", an item the list above also
  did not ask

### 3. The cohort move is NOT attributable to the repair

`cohortManagers` 2,396 -> 2,397 is the historically-expected figure, and it is
tempting to read it as the repair restoring the cohort. That claim is not
supported and is not made. Two `Bootstrap Sharp Records` crawls (`33335284902`
21:02-21:42Z, `33336384174` 21:25-22:23Z) rewrote the sharp ledger between the
two measurements, and `eligibleRosters` moved 9,529 -> 9,493, which scoring
cannot cause. The scoring claim rests on the byte-identical proof above, not on
comparing two production counts across a ledger rewrite.

### 4. Open, recorded, not folded into this row

Lane 4's **remote** `C1` timed out on `GET /api/sharp/market` in run
`33347132201`, which also blocked `C2`/`C3`. That is a different endpoint from
this row's, and the same check **passes on-box** in `33348027841` — so it reads
as an HTTP-path latency symptom rather than a data defect. It shares
`cohort_members` with the endpoint optimized here, which makes it the plausible
next Sharp lever. It is not part of V1-61's recipe and nothing here claims it.

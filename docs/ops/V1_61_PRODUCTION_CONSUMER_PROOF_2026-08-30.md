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

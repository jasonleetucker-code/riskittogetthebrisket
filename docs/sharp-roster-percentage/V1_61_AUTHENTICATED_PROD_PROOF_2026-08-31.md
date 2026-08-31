# V1-61 authenticated production proof — 2026-08-31

This record preserves the post-correctness-repair production evidence for `V1-61` (Sharp Roster Percentage). It does not by itself change the V1 completion contract or denominator.

## Correctness lineage

The scoring correctness repair is merge SHA `b6559ac47ca54179f23b02af198867fb0e6c38dd` (`#1189`, `fix(sharp): restore championship-base tie invariant (V1-61)`). `Deploy Production` run `33334198055` completed successfully on that exact SHA.

The fresh authenticated verification ran from `main` SHA `0b4514b1f504015f422fcf02c51df9a5b274c8e6`. GitHub compare reports that head is 8 commits ahead of `b6559ac47...` and 0 behind. The intervening diff is data/refresh output; no competing Sharp scoring implementation is introduced.

## Intended production consumer

`V1 Authenticated Production Verification (ephemeral guest session)` run `33347132201`, job `99353284814`, exercised the real production endpoint and canonical guest-pass login path. The pass was revoked after the run.

Dedicated check `V61A` returned **PASS** for `V1-61`: `sharp roster-percentage transparency fields, null never zero`.

Observed typed, populated production values:

- `cohortCoveragePct = 0.7597`
- `cohortManagers = 2397`
- `eligibleRosters = 9493`

The verifier recorded: `transparency block present with typed coverage (cohortCoveragePct=0.7597, cohortManagers=2397, eligibleRosters=9493)`.

This is the first acceptable V1-61 consumer proof after `#1189`; the earlier pre-repair V61A success remains historical only and is not reused.

## Whole-workflow red is not a V1-61 failure

Run `33347132201` concluded `failure` because the subsequent Lane 4 remote sweep hit an unrelated timeout while checking `V1-63` and retained truthful blocked/unmeasurable states for other Lane 4 checks. The dedicated authenticated API verification step itself succeeded and `V61A` passed. This record therefore does not collapse workflow status into row status.

## False-green controls

- No auth bypass or admin elevation was introduced.
- Missing values were not coerced to zero.
- The prior scoring-regression evidence invalidating the older consumer proof is preserved.
- `MERGED`, `DEPLOYED`, and `VERIFIED` remain distinct states.
- This file records evidence only; canonical promotion must still follow the completion contract's reconciliation/CI rules.

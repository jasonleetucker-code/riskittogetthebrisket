# Why deploy runs show up CANCELLED, and when that is not benign

**2026-08-20, Integration.** Closes a question left open by the #930 incident,
where a merged P1 fix was found never to have deployed and the record said the
cancellation's *root cause was never established*.

## The mechanism

`.github/workflows/deploy.yml` declares:

```yaml
concurrency:
  group: production-deploy
  cancel-in-progress: false
```

`cancel-in-progress: false` is usually read as "nothing gets cancelled". That is
not what it means. It protects the **running** deploy — which is the point, since
half-applying a deploy is worse than delaying one — but GitHub keeps at most
**one pending run per concurrency group**. When a third run arrives while one is
running and one is queued, the *queued* one is cancelled and the newest takes its
place.

So on a night of rapid merges the pattern is:

| run | head | outcome |
|---|---|---|
| 2506 | `e37d2786e` (#934) | running → **success** |
| 2507 | `3ce65116c` (#941) | queued → **cancelled** |
| 2508 | `c2eb9a79f` (#935) | queued → **cancelled** |
| 2509 | `b949f8f04` (#925) | queued → runs next |

Measured verbatim on 2026-08-20 03:15–03:22 UTC.

## Why it is normally benign

Deploys ship a tree, not a patch. The surviving run's head **contains** every
commit the cancelled runs would have shipped, because they are all ancestors on
`main`. Cancelling a superseded queued deploy loses nothing.

## When it is NOT benign, which is the #930 case

The guarantee has one condition: **the last run in the chain must actually
succeed.** If merging continues faster than a deploy completes, the queue is
starved indefinitely and *nothing* reaches production while every individual
merge looks fine. And if the final run fails or is cancelled by yet another
merge, the whole batch silently stays undeployed — which is exactly how #930's
fix was merged, reported as done, and not running.

A cancelled run and a failed run report the same "not green", and neither is
distinguishable from "not started" if nobody looks.

## Operational rule

- **Merged is not deployed.** Never promote a production-level V1 row from a
  merge; read the deploy run's `Deploy To Production` job, and specifically its
  `Post-deploy smoke test` and `Validate live data contract` steps.
- **Stop merging to let a deploy land** before doing production verification.
  On 2026-08-20 this was done deliberately after #925; run 2509 then completed.
- **Identify the run by head SHA**, not by "the latest deploy". The run that
  matters is the one whose head contains the commit you care about.
- A cancelled *queued* run needs no action. A cancelled *running* run does.

## The related gap, unchanged

No endpoint publishes a build identifier — `/api/status`'s `contract.version`
is the payload **shape** (`2026-03-10.v2`), not the commit. Recorded by #932.
Until that changes, "is my change live?" is answered by finding a payload value
that could only come from the new code. Worked example from the same night:
`AWARDS_UNAVAILABLE_NO_GAMES` is absent at `5feade0eb^1` and present at
`5feade0eb`, so production returning `season_has_not_played_a_game` proved the
deployed build contained #937.

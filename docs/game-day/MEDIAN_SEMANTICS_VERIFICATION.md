# Sleeper median-game semantics — verification record

**Status:** RESOLVED for the owner's 12-team league and other even-sized
Sleeper leagues by authoritative host documentation, 2026-09-06.

`docs/GAME_DAY_PROBABILITY_SPEC.md` §3 requires the league-median
threshold and exact-tie behavior to be host-faithful rather than guessed.
Contract row `W1-23` depends on that evidence.

## Authoritative host evidence

Sleeper's own support article is the authority used here:

- **Sleeper HQ, "Extra Game Each Week Against League Median"**
- published **2024-03-26**
- verified/retrieved **2026-09-06**
- https://support.sleeper.com/en/articles/3971690-extra-game-each-week-against-league-median

The article settles the two facts that were previously blocked:

1. the extra regular-season result is against the **league median**;
2. for an even-sized league, the median is the average of the two middle
   weekly team scores;
3. a team whose score is exactly equal to that median receives a **tie**,
   not a win or a loss.

The owner's league has 12 teams, so this directly settles W1-23's
current-league threshold and tie semantics.

### Honest boundary: odd-sized leagues

The article describes the median using the middle **two** teams and gives
10-team and 12-team examples. It does not explicitly state Sleeper's
behavior for an odd number of fantasy teams.

The simulator therefore does **not** extend the evidence beyond what the
host documented: `threshold_semantics_verified` is true only for the
canonical `"median"` rule on an even-sized simulated league. An odd-sized
league remains unverified until authoritative host evidence establishes
that case.

## Earlier retrospective attempt — preserved, not used as authority

Before the host documentation was located, the repository tried to infer
the rule retrospectively from the owner's 2025 Sleeper league.

What that attempt established remains useful:

- `league_average_match = 1` on the owner's 2026, 2025 and 2024 leagues;
- 2025 standings contained two decisions per regular-season week, proving
  that the extra weekly standings result was active.

What it could **not** establish was median-vs-mean or exact-tie behavior.
Six candidate reconstructions reproduced at most 3 of 10 teams' recorded
2025 results.

The load-bearing reason was historical drift: Sleeper's currently stored
best-ball matchup points no longer reproduce Sleeper's own season totals.
Across sampled teams, reconstructed regular-season points were hundreds of
points short of the stored season totals. In a best-ball format, later stat
corrections can also change the optimal lineup, so reconstructing what the
host decided at the time from today's historical point rows is not a sound
authority for this rule.

That failed reconstruction is retained here because it explains why the
repository must prefer direct host documentation over reverse-engineering
mutable historical data.

## Canonical implementation disposition

`src/ros/game_day_sim.py` now follows the verified evidence:

- `THRESHOLD_SEMANTICS = "median"`;
- Python's `statistics.median` gives the documented average of the middle
  two scores for an even-sized league;
- `Beat League Median %` counts only scores strictly above the threshold;
- an exact-median score is a **tie** and is not silently folded into a
  median-loss joint bucket;
- the provenance flag is true only for the verified canonical median
  semantics on an even-sized league;
- an explicit non-canonical `"mean"` override remains visibly unverified;
- the semantic repair is versioned as `game-day-sim-v2`;
- `MODEL_VERSION` participates in the disk-cache fingerprint, so a deployment
  cannot reuse a pre-v2 cached simulation merely because roster/projection
  inputs are unchanged.

The four optional joint buckets in the product spec describe win/loss
combinations only (2-0, the two 1-1 paths, 0-2). A draw containing a
median tie is therefore excluded from those win/loss buckets rather than
misrepresented as a loss.

## W1-23 disposition

The **methodology/evidence blocker is resolved** by the authoritative
Sleeper source above. W1-23 should be promoted to `VERIFIED` only when
the bounded code/tests carrying that rule have passed the repository's
required integration evidence and the contract tally is updated
mechanically. This document alone is not a green-CI or merged-code claim.

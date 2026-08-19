# Lane 4 — production verification package

**Status: this is an instrument, not evidence.** Nothing here claims any V1 row
is verified. Running it produces evidence; writing it down does not.

The runnable half is **`scripts/verify_lane4_production.py`**. This document is
what each check proves, what it deliberately cannot prove, and how to read a
result without over-claiming.

---

## Why a script rather than a checklist

The prose checklist that shipped in `#927`
(`docs/lane4/L2_L3_VERIFICATION_PROCEDURES.md`) named endpoints and fields that
**do not exist** — `POST /api/faab/recommend` (the real route is
`/api/waiver/faab-recommend`) and roster-percentage fields like
`rostersObserved` that the payload never had. Several of its steps are
unrunnable as written.

That is not a typo problem, it is a *method* problem: a checklist's paths are
checked by a reader's goodwill, a script's are checked by execution. Every path
and field below is resolved against the deployed code at run time, so this class
of error fails loudly instead of silently producing an unrunnable procedure.

**Both defects are in `#927`, which is frozen.** They are flagged there for
Integration; this package supersedes those endpoint and field references.

---

## The three rules, enforced in code

1. **Production authentication is never bypassed.** `/api/sharp/*` and
   `/api/waiver/*` are session-gated and correctly so. The script sends a cookie
   only if the operator exports `RISKIT_SESSION_COOKIE`. There is no fallback
   credential, no test-mode header, no allowlist edit — pinned by
   `test_no_cookie_means_no_cookie_header`.

   **A 401/403 is `UNVERIFIABLE_UNAUTHENTICATED`**: insufficient evidence,
   deliberately neither a pass nor a failure. It raises a dedicated
   `Unauthenticated` type so no generic handler can downgrade it to a transient
   error. The vocabulary is the one
   `.github/workflows/verify-sharp-production.yml` already uses.

2. **Nothing is fabricated.** No cohort, ledger, scoring card, crowd row or
   player is invented. `--add-player` must name a real free agent; without it the
   crowd checks report `BLOCKED` rather than guessing one.

3. **Read-only.** GETs, a POST that computes a recommendation without persisting
   one, file reads, and `systemctl list-timers`. Nothing writes to production.

### The status vocabulary is the point

| status | meaning |
|---|---|
| `pass` | the case under test arose and behaved correctly |
| `fail` | the case arose and behaved incorrectly |
| `inapplicable` | the input was read and **did not contain the case**. Not a pass |
| `blocked` | a required input does not exist here. Not a pass, not a failure |
| `unverifiable_unauthenticated` | 401/403. Not a pass, not a failure |
| `error` | the check did not run |

Exit codes: `0` at least one real pass and no failures · `1` error · `2` failure
· **`3` nothing was proven** — every check was blocked, unauthenticated or
inapplicable.

`3` exists because it is the whole risk. A run where nothing could be measured
must not share an exit code with a run where everything passed, and
`test_a_run_that_proves_nothing_does_not_exit_zero` pins it.

---

## Modes

Neither subsumes the other; the package is both.

| | `--mode remote` | `--mode onbox` |
|---|---|---|
| runs | anywhere, over HTTPS | in the deployed working directory |
| needs | `RISKIT_SESSION_COOKIE` | filesystem + deployed source |
| sees | what the API publishes | the scoring card, the crowd ledger, systemd |
| covers | C1–C3, C8, C9 | C1–C9, V1-57/60/65 |

The scoring card (`data/leagues/scoring_<id>.json`) and the crowd ledger
(`data/faab/crowd_history_<league>.json`) are gitignored and prod-only, so
**C4–C7 are structurally impossible over HTTP** and say so rather than
approximating.

```bash
# on the box
python scripts/verify_lane4_production.py --mode onbox \
    --league dynasty_main --origin http://127.0.0.1:8000 \
    --add-player '<a real free agent>' --out data/ops/lane4-verification.json

# from anywhere
export RISKIT_SESSION_COOKIE='session=...'
python scripts/verify_lane4_production.py --mode remote \
    --origin https://chaseupside.com --league dynasty_main \
    --add-player '<a real free agent>'
```

---

## The #927 checks

`#927` is not deployed yet, so this package is a **before/after instrument**.
Run it now to establish the baseline, and again after the deploy. Measured on
the two trees today:

| check | on `main` (pre-#927) | on `#927` |
|---|---|---|
| C4 TEP rule | **`fail`** — label rule detected | `inapplicable` — card rule detected, no fresh card here to compare |
| C5 unproven scoring | **`fail`** — no `unprovable_target_fields` owner | **`pass`** |

That discrimination is the package proving it can tell the builds apart, and it
was obtained without fabricating anything.

### C1 — zero-voter `personManagerQuality` is JSON `null`, never `1.0` *(V1-63)*

Reachable whenever every person who touched an asset both added **and** dropped
it inside the window: the row is still emitted, with `personVotes: 0`. `1.0` is
the *highest* possible manager quality, so the pre-#927 build answered "how good
is the evidence?" with a green light precisely when there was none.

`pass` = every zero-voter row published `null`. `fail` = any published a number.
`inapplicable` = rows exist but none had `personVotes == 0`. `blocked` = no row
carried `personConsensus` at all (empty cohort or empty ledger).

**#920 named this as the blocker to V1-63 `VERIFIED`**: *"`personManagerQuality`
still returns `1.0` for zero voters."*

### C2 — a measured `0.0` stays `0.0` *(V1-63)*

The repair must not overshoot. UNKNOWN and WORST are different answers, and a
cohort of voters all scored `0.0` **has** an answer: the floor. Any row with
voters and a `null` quality means a real measurement was swallowed → `fail`.

### C3 — `networkConcentration` is `null` with no weighted volume *(V1-63)*

It is a *share* of weighted volume. With no weighted volume there is no share for
any network to hold, and `0.0` is the one value that reads as its exact opposite:
"no single network dominates".

### C4 — target TEP comes from the card, not the profile label *(V1-129)*

Reads **which rule the deployed build implements** from
`TargetFormat.from_roster_settings`'s own signature (`scoring_settings` = card,
`scoring_profile` = label), then checks that the served `tep` equals what the
league's own fresh card measures via
`league_intel.te_premium.measure_te_demand`.

Signature-first on purpose: a behaviour-only check passes on a label-rule build
whenever the label happens to agree with the card.

### C5 — stale or missing scoring evidence leaves TEP UNKNOWN and fails closed *(V1-129)*

A card proves when it was taken, not that it is still true. `pass` requires all
three: evidence is not `fresh`, `tep is None`, and the target reports `tep` among
its unprovable fields so classification hard-excludes rather than assuming a
match.

**UNKNOWN must not become "no TE premium"** — that would admit a whole population
of offense-scoring leagues as comparable.

When the card *is* fresh this is `inapplicable`, and the detail says explicitly:
do **not** age or delete a card to manufacture the case.

### C6 — `dynasty_main` behaves as non-TE-premium under its actual card *(V1-129)*

The specific measured claim, kept separate from C4 because a build can read the
card and still get this league wrong. Asserts the card's own numbers
(`bonus_rec_te`, `bonus_fd_te` against their WR counterparts) and that the served
value follows them.

If the card *does* show a TE edge, this reports `inapplicable`, not `fail` — the
commissioner may have restored the premium, and that is a finding about the
league rather than about the code.

### C7 — comparable crowd population, card-derived vs the retired label rule *(V1-129)*

A counterfactual over **real stored rows**, not a simulation: the accumulated
ledger is classified twice — once against the served target, once against the
same target with `tep` forced to what the retired label rule would have said.
The only thing that varies is the policy.

Reports `rowsUsed`, `tierCounts` and `excludedCounts` for both. Where card and
label disagree, every row in the difference was being compared on a TE premium
this league does not grant.

### C8 — the refusal is specific, and names the right side *(V1-129)*

"We hold no crowd evidence" and "we cannot describe our own league well enough to
judge any" are different failures with different fixes. A build with no
`targetFormatUnknown` key `fail`s: the two states are indistinguishable to a
consumer. An undescribable target must answer
`target_format_unverifiable:<fields>` **ahead of** the freshness checks, because
freshness is moot when no row is admissible.

### C9 — the crowd moves the bid only when it was actually admitted *(V1-129)*

The crowd feeds `rival_bid_cdf` at weight **0.6**, so what it admits moves real
recommended bids. Two directions, both `fail`:

* admitted and priced, but **no** `Cross-league market` factor row → the evidence
  moved the bid invisibly;
* refused, but the factor row is **still there** → the refusal is cosmetic.

Matched on the factor's stable `label`, not its prose, so improving the wording
does not break the check. `standard` / `conservative` / `aggressive` / `max` /
`contention.clearing` are recorded so two runs measure the effect directly.

---

## The other Lane 4 rows

**V1-57 (L3)** — `dynasty-faab-history` installed *and fired* (`systemctl
list-timers`), plus the artifact it produces
(`data/faab/bid_history_<league>.json`, fresh inside 25 h against a daily timer).
A green manual run of the script does **not** satisfy this row: that the script
works was never the open question.

**V1-60 (L2)** — the FFPC lane is real or honestly unavailable.
`CollectResult` must carry `status`/`unavailable()`, and `cohortCoveragePct` must
be `null` — never `0` — when nothing was observed. With an empty cohort the check
reports `blocked` and names V1-58 as the blocker, because the honest-degraded
half is only half the row.

**V1-65 (L2)** — exactly one `cohort_members` definition, in
`src/sharp/cohort.py`. Deterministic, so it runs anywhere; a second definition is
how this row regresses.

**V1-58 / V1-59 — BLOCKED, and stated as such.** Both need production Sharp
evidence and the recorded artifacts end at `401` /
`unverifiable_unauthenticated`. `/api/sharp/*` is not in the public allowlist
(`tests/sharp/test_public_api_allowlist.py` pins that) and **that gate must not be
relaxed to make verification easier**.

The single credential that unblocks both is an authenticated admin session for
the deployed origin, held by the site owner. With it: V1-58 is
`GET /api/sharp/cohort` returning a non-empty membership against the deployed
SHA; V1-59 is a clean `journalctl` run of `dynasty-sharp-discovery` (04:20) →
`dynasty-sharp-records` (04:50) → `dynasty-sharp-rosters` (05:50) with no FFPC
timeout and no SQLite lock.

Neither is to be closed by standing up a synthetic cohort. **A manufactured
population would verify the manufacture.**

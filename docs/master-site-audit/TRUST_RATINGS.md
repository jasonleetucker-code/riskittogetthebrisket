# Final Trust Assessment

Deliverable section 20 of the audit brief: a separate rating for each named subsystem, with the
reason.

Ratings use the brief's scale: **Trustworthy · Mostly trustworthy · Use with caution · Not
trustworthy · Not implemented · Unverifiable**.

Two rules applied throughout, because they change several ratings:

- **A rating describes what a user sees, not what the code intends.** A correct engine whose
  output is overridden before it reaches the screen rates on the screen.
- **"Unverified" is not "wrong."** Where this environment could not test something, the rating
  is *Unverifiable* and says what would settle it — it is not downgraded for being untested,
  and it is not credited either.

Counts below come from `evidence/trust-rollup.json`, generated from `findings.json`. `ver` is
how many of a subsystem's findings went through adversarial verification.

| Subsystem | Rating | n | P0 | P1 | ver |
|---|---|---|---|---|---|
| Scoring | Mostly trustworthy | 5 | 0 | 3 | 3 |
| Player identity | Use with caution | 15 | 0 | 2 | 1 |
| Market data | Mostly trustworthy | 30 | 0 | 8 | 1 |
| Consensus | Use with caution | 51 | 1 | 11 | 4 |
| Fundamental values (BDVM) | Unverifiable | 17 | 0 | 3 | 0 |
| League-adjusted values | Not trustworthy | 9 | 1 | 3 | 1 |
| Rankings | **Not trustworthy** | 16 | 2 | 4 | 2 |
| Trade Calculator | **Not trustworthy** | 15 | 1 | 5 | 1 |
| Roster Analyzer | Use with caution | 10 | 1 | 5 | 1 |
| Trade Finder | Use with caution | 16 | 0 | 7 | 3 |
| Buy/Sell Tracker | **Not trustworthy** | 18 | 1 | 7 | 5 |
| Consensus Edge | Mostly trustworthy (switched off) | 10 | 0 | 0 | 1 |
| Sharp Tracker | Use with caution | 22 | 0 | 1 | 0 |
| Insider Trading | Unverifiable | 16 | 0 | 0 | 0 |
| FAAB | **Not trustworthy** | 22 | 1 | 5 | 2 |
| ROS | **Not trustworthy** | 11 | 2 | 0 | 2 |
| Playoff and championship odds | Not trustworthy | 2 | 0 | 0 | 0 |
| Rookie picks | Use with caution | 17 | 1 | 3 | 2 |
| Perfect Draft | Use with caution | 17 | 1 | 3 | 2 |
| Schedule | **Not implemented** | 1 | 0 | 1 | 0 |
| Public League Page | Use with caution | 18 | 0 | 4 | 1 |
| Historical records | Use with caution | 23 | 0 | 3 | 5 |
| Performance | Use with caution | 14 | 0 | 5 | 3 |
| Security | Mostly trustworthy | 10 | 0 | 4 | 1 |

---

## The ratings, explained

### Scoring — Mostly trustworthy
The exact-scoring stack is one of the better-built parts of the platform, and the league config
matches the host on the settings that were checkable. It does not rate higher because scoring
constants are implemented in more than one module rather than behind one service, and because
`src/nfl_data/realized_points.py` disagrees with the host on a measured share of player-weeks
(W18-F003, rescoped but upheld in substance). Golden fixtures exist for the pieces tested here;
they do not cover every event-stacking combination.

### Player identity — Use with caution
Identity resolution mostly works, and the audit did not find two different players merged into
one. What it did find is name-based joins surviving where a stable id exists — including at
display-join time on `/draft` and the `/rankings` fundamentals column — so rows silently fail to
join rather than joining wrongly. That is the safer failure mode, but it is invisible: a missing
row looks like a player with no data.

### Market data — Mostly trustworthy
The two retail anchors (KTC for offense, IDPTradeCalc for IDP) ingest, refresh and carry votes on
the live board, and the source-health surfaces broadly tell the truth about them. Coverage is
genuinely partial and the platform knows it: KTC carries 590 of 1,074 players, IDPTradeCalc 898.
Eight P1s concern staleness handling and failure behaviour rather than the values themselves.

### Consensus — Use with caution
The blend spine is real and better than the surrounding documentation suggests: it is
deterministic, monotonic, and the single-source haircut, corridor clamp and count-aware
aggregation all do what they claim. The rating is held down by one thing — the board a user
*sees* is not this board (see Rankings) — and by a long tail of defects in the layers stamped
around the values (confidence buckets, market-gap direction, tiering).

### Fundamental values (BDVM) — Unverifiable
`data/bdvm/` does not exist in this container, so no numeric claim about BDVM could be tested.
What *was* provable is favourable: the engine's structural isolation from market inputs holds,
the "unpriced with a reason" contract is honoured rather than fabricating values, and the
dependent UI self-suppresses when the engine has no data. **What would settle it**: run
`scripts/bdvm_build_baseline.py` on a host with nflverse access and re-run the parity fixture.

### League-adjusted values — Not trustworthy
The overlay is the mechanism that is supposed to reprice the board for this league, and W07-F001
shows the shipped board never takes the measured path. Separately, the lens is a silent no-op on
all-offense trades (W09-F006) and is stamped `valuationMode: leagueAdjusted` on responses where a
large share of asset legs were never repriced (W29-F002). A label that says a lens was applied
when it was not is worse than no lens.

### Rankings — Not trustworthy
**The board `/rankings` renders is not the board `GET /api/data` serves.** Every page load, for
every user, posts `tep_multiplier=1.15`, which flips the request onto the override path and
bypasses the backend's measured ADR-015 TE-basis curve. Measured consequence: 627 of 740 ranks
and 654 tiers differ from the served contract, tight ends are under-priced by up to 21.2%, and
the response stamps `isCustomized: false` while it happens (W03-F001, W07-F001).

The cause is two lines that disagree: `useSettings.js:35` defaults `tepMultiplier` to `1.15` — a
concrete number — while `dynasty-data.js:919-923` treats *any* finite number as a deliberate
operator override. There is no value the default could take that would be read as "auto" except
`null`, and a migration at `useSettings.js:182-190` actively rewrites `null` to `1.15`. Users who
were in auto mode were migrated out of it permanently.

This is the highest-value repair in the audit and it is size S.

### Trade Calculator — Not trustworthy
Same root cause, different surface (W08-F001, upheld): the calculator never sums the canonical
board. Its own internal mechanics are sound — A→B/B→A symmetry holds, the KTC VA port matches its
JS source — so this rating should move as soon as the TEP override is fixed. Until then every TE
in every package is priced up to 21% below what the backend believes.

### Roster Analyzer — Use with caution
Real roster modelling with real lineup awareness, but it inherits the ROS defect below on the
Trade Deadline surface (W20-F002), and several of its inputs are partial. Team-direction
classification has more than one implementation and they do not always agree.

### Trade Finder — Use with caution
No P0s survived here, and the engines produce real, defensible packages. The rating reflects
seven P1s: coverage gaps by team, package shapes that never generate, and controls whose effect
on candidate generation is weaker than the UI implies. Notably, the prior audit's claim that the
finder is still offense-only did **not** reproduce as stated.

### Buy/Sell Tracker — Not trustworthy
There is no central Buy/Sell Tracker. There are 16 label emitters, 14 of them reachable, with 5
competing threshold sets and nothing reconciling them (W12-F003). The clearest symptom is
W12-F002 (upheld): the `/rankings` Edge column labels **32 of 35 top-250 tight ends SELL, and
every single SELL in the top 250 is a tight end** — the column is measuring TE-premium basis
mismatch, not mispricing. A user is being told to sell every tight end he owns.

### Consensus Edge — Mostly trustworthy, and switched off
The best-evidenced subsystem in the audit: 4 of its 10 findings are `Implemented and verified`,
no P0s, no P1s. Its own decision record concluded the composite had not earned its place and
turned the flag back off (ADR-023), and the code is consistent with that. Rating describes the
code, which is sound; it is not currently serving users.

### Sharp Tracker — Use with caution
The cohort definition is genuinely single-sourced and the roster-percentage methodology is
honest about denominators. Twelve defects concern qualification and counting, and no sharp ledger
exists in this container, so the numeric behaviour of a populated cohort is untested here.

### Insider Trading — Unverifiable
`data/intel/` and the platform ledger database do not exist here, so five of seven routes return
a clean `data_not_ready` 503. That is honest degradation and it is the right behaviour. Nothing
about populated behaviour could be tested. **What would settle it**: the intel refresh on a host
with the ledger.

### FAAB — Not trustworthy
Your report that recommendations run too aggressive is confirmed, with a specific cause
(W11-F001, upheld): position calibration blends **raw dollar bids from three seasons whose
budgets were $1000, $200 and $100**, with no normalization. The RB anchor is inflated ~5x — 43.0
against a budget-normalized 8.58 — and that average is blended 50/50 into every recommendation
for a position with 3+ historical bids, which is all 8 positions. Replacement-level running backs
draw $22–$32 bids on a $100 budget.

### ROS — Not trustworthy
Two upheld P0s, and the first is a one-line type error: `sorted(snapshot.seasons,
key=luck._season_sort_key)` passes objects to a function typed for strings, so every season
sorts equal and the sims run on the **oldest** loaded season — 2024. Every number on
`/league → Championship` and `/league → Trade Deadline` is a replay of a season that ended ~20
months ago. Downstream, absence from that stale sim is coerced to 0.0 playoff odds, so the
strongest roster in the league (100th-percentile ROS strength) is told **"Seller — sell aging
win-now players."** Four of twelve managers get inverted advice. The fix is size XS.

### Playoff and championship odds — Not trustworthy
Rated on inheritance rather than on its own defects: the simulator is reasonable, but it is fed
by the ROS season-selection bug above, so its published numbers describe the wrong season. Only
two findings landed here directly, which is itself a coverage gap worth noting.

### Rookie picks / Perfect Draft — Use with caution (both)
They share a P0 (W10-F002, upheld): `mergeDraftCapitalTeams` hard-caps every team's slot count at
6, so a team owning 31 of the 72 live picks renders as "0/6 slots" with a 5.2x-wrong $/slot, and
after six picks the app declares the draft over for them. Your requirement that the optimizer
carry **no fixed slot count** is therefore violated in the most literal possible way. Separately,
pick values are largely point estimates rather than the distributions you asked for.

### Schedule — Not implemented
There is no schedule generator anywhere in the repository — no route, no module, no script, no
constraint solver. Not partially built, not scaffolded: absent. The 14-game / 3-division /
no-back-to-back / Jason-vs-Michaela-week-4 specification has no implementation to audit.

### Public League Page — Use with caution
It renders, the tabs are real, and the deep links work. The caution is about *labelling*: several
all-time claims rest on data the platform does not have, and the brief's rule — public outputs
must not present missing history as complete — is not consistently met. See
`HISTORICAL_DATA_GAPS.md` for the page-by-page list.

### Historical records — Use with caution
Best-evidenced of the "caution" group (5 verified findings). Current-state data is strong; history
is partial in specific, nameable ways. The most consequential structural gap: all-time franchise
player leaders require weekly player scores joined to **week-level roster ownership**, and that
join is not consistently what the code does.

### Performance — Use with caution
Nothing here produces a wrong number, which is why it is not lower. But `/api/bdvm/roster` takes
**48 seconds** to return 310 bytes, `/api/league-comparison` 26.6s, `/api/draft-capital` 13.2s,
and `/api/data` ships **11.95 MB** uncompressed against a documented "~4 MB". The mobile
"compact" view is **13% larger** than the desktop view it is supposed to shrink (W26-F001,
upheld) — mobile users download more, not less.

### Security — Mostly trustworthy
Auth and the admin allowlist hold up; the API 401s correctly across the board and admin routes
403 for a non-allowlisted session. Four P1s concern the public/private boundary rather than
authentication — chiefly that `/api/draft-capital` returns real pick dollar values to an
anonymous caller, and that the rate limiter trusts a client-supplied `X-Forwarded-For`. Rate
limiting itself could only be tested on a separate un-bypassed backend, since the audit harness
bypasses it on the shared stack.

---

## Two things worth saying plainly

**58 findings are `Implemented and verified`.** The blend spine is deterministic and monotonic;
Consensus Edge is well-built; BDVM's market isolation is structurally real; the test suite runs
green at 6,278 Python tests and 1,754 frontend tests; the production build passes its own bundle
budgets. This is not a codebase in disarray. It is a well-built engine with a small number of
defects sitting exactly where the user reads the output.

**Four of the nine surviving P0s are two bugs.** The TEP default (size S) closes W03-F001,
W07-F001, W08-F001 and materially changes W12-F002. The ROS sort key (size XS) closes W17-F001,
W17-F002 and W20-F002. Two small diffs move Rankings, Trade Calculator, ROS and the odds board
off *Not trustworthy*. That is the single most important sentence in this audit.

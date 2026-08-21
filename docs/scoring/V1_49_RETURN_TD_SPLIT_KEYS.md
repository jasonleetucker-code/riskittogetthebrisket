# V1-49 — the four disputed Sleeper return-TD keys (#1020 vs #1027 reconciliation)

2026-08-21. Claude 3 — Season/Scoring/BDVM, V1 numerator sprint. Docs +
code, no other unit touched.

## Reconciliation: #1020 and #1027 do not disagree

Two prior sessions reached apparently different V1-49 conclusions:

- **#1027** concluded #915's engine-level special-teams repairs (SAF
  normalization, blocked-kick scoring, the season-card resolver) are
  correct and in place, and that the remaining V1-49 gate is the
  `host_native_scoring` promotion path, not a code defect.
- **#1020** found four Sleeper scoring keys — `kick_ret_td`,
  `punt_ret_td`, `idp_def_pr_td`, `idp_def_kr_td` — with no canonical
  realized-scoring path on the champion `nflverse` source.

Traced against current `main` (`54a70883e`): **both are correct, and
they audit disjoint residuals.** #1027 never claims these four keys are
scored; #1020 never disputes #915's fixes. Neither audit needs to be
chosen over the other.

## The four keys, resolved

| key | verdict | mechanism |
|---|---|---|
| `punt_ret_td` | real, distinct, **repaired** | nflverse's weekly feed already carries this as a bare column, `pt_return_tds` — confirmed against the live 2025 release header. Added to `realized_points._SIMPLE_KEYS`, same tier as `kr_yd`/`pr_yd`/`st_td`. No play-by-play involved. |
| `kick_ret_td` | real, distinct, **repaired** | no weekly-feed column exists (only the combined `special_teams_tds`); derived from raw PBP (`play_type=="kickoff"` + `return_touchdown`, credited to `kickoff_returner_player_id`, excluding `own_kickoff_recovery_td`). Added to `realized_points.PBP_SUPPLEMENT_KEYS` and `src.nfl_data.pbp_weekly._iter_plays`, mirroring the existing `pass_int_td` predicate exactly. |
| `idp_def_pr_td` | **closed as unsupported** | Sleeper's own documented scoring UI has no IDP return-TD category — return TDs are Special-Teams-Player only (`kick_ret_td`/`punt_ret_td` above, whose `RULE_META` bucket already includes `DB`). No sampled 2025 host dump (~330 player-entries, REG wk5/9/14) ever carries this key nonzero. No host-truth instance exists to validate a predicate against, so none was written. |
| `idp_def_kr_td` | **closed as unsupported** | same reasoning as `idp_def_pr_td`. |

Neither IDP key is added to `DERIVABLE_FROM_PLAY_BY_PLAY` or
`HOST_PUBLISHED` — both would misrepresent this as a recoverable gap
rather than the investigated, proven-unsupported finding it is. If a
future session obtains a real nonzero instance of either key, that is
new evidence and reopens this as its own investigation.

## No-double-count behavior (explicit determination)

`kick_ret_td`, `punt_ret_td` and `st_td` are three **independent** keys
in Sleeper's own scoring vocabulary, each sourced from a different,
non-overlapping mechanism in this engine:

- `st_td` reads the weekly feed's `special_teams_tds` column (combined
  kick+punt count).
- `punt_ret_td` reads the weekly feed's separate `pt_return_tds` column.
- `kick_ret_td` reads a PBP-derived per-play predicate
  (`play_type=="kickoff" && return_touchdown`), entirely independent of
  either weekly column.

**If a league configures nonzero rates for `st_td` AND `kick_ret_td`
(or `punt_ret_td`) simultaneously, the same physical return-TD event
pays under both keys.** This is a deliberate, verified non-bug, not an
oversight: it is the identical stacking shape this codebase already
treats as correct for `kr_yd` (return yardage) plus `st_td` (return-TD
bonus) — a league paying both a per-yard rate and a TD bonus for the
same play is standard fantasy scoring design, the same way `rec_yd` and
`rec_td` both pay on one catch. Sleeper's own scoring engine does not
enforce mutual exclusivity between a combined category and its splits
at the config level, and this engine's job is to score whatever
nonzero rates a league's real `scoring_settings` contains — faithfully,
not policed against a stacking choice that is the commissioner's to
make. **Verified**: neither live league (`dynasty_main`, `dynasty_new`)
configures more than one of these three keys nonzero today (see the L2
measurement below), so this stacking is not presently reachable on any
league this platform serves — recorded as the correct behavior for a
league that does, not as a live discrepancy.

What IS guarded against, by test, is a different failure mode: a single
PBP play being credited to the WRONG one of the two split keys.
`test_kick_ret_td_does_not_fire_on_a_punt_return_touchdown` pins that a
punt-return-TD play never credits `kick_ret_td`, and the `pt_return_tds`
weekly column is punt-return-specific by nflverse's own definition, so
the two split keys cannot double-credit each other on the same event
either.

## Host-truth validation

Per this repo's established discipline (predicates are measured, not
designed — see `src/nfl_data/pbp_weekly.py`'s own module docstring),
both repaired keys were validated against real 2025 events before being
written down, not merely unit-tested against synthetic data.

**`kick_ret_td`** — player 10228 in
`docs/master-site-audit/evidence/W18/sleeper_stats_2025_wk9.json`
(`st_td: 1`, `kr_yd: 179`, `kr_lng: 98`) resolves to Charlie Jones
(Sleeper `10228`, GSIS `00-0038576`, CIN WR). The real 2025 PBP release
shows exactly one `play_type=="kickoff"` row for that GSIS in week 9
(`game_id 2025_09_CHI_CIN`) with `return_touchdown=1`,
`own_kickoff_recovery_td=0`, `return_yards=98` — matching `kr_lng`
exactly — and his three other kickoff returns that week (28, 23, 30
yards) sum with the touchdown return to 179, matching `kr_yd` exactly.
Derived `kick_ret_td = 1`, matching the host's `st_td = 1`.

**`punt_ret_td` vs `kick_ret_td` discrimination** — week 14, three real
`st_td` scorers on `sleeper_stats_2025_wk14.json`:

| Sleeper id | player | GSIS | PBP play type | derives to |
|---|---|---|---|---|
| 8676 | Rashid Shaheed | 00-0037545 | `kickoff` | `kick_ret_td` |
| 9494 | Marvin Mims | 00-0038976 | `punt` | `punt_ret_td` |
| 11608 | Isaiah Williams | 00-0039451 | `punt` | `punt_ret_td` |

All three confirmed directly against the real 2025 PBP release (exact
play descriptions: Shaheed "98 yards, TOUCHDOWN" off a kickoff; Mims "48
yards, TOUCHDOWN" and Williams "78 yards, TOUCHDOWN" both off punts).
`kick_ret_td` derives to exactly 1 for week 14, and
`kick_ret_td + punt_ret_td == st_td` (1 + 2 == 3) holds — the identity
`tests/nfl_data/test_pbp_weekly.py::test_kick_ret_td_reconciles_against_combined_st_td`
pins, since Sleeper never publishes the split itself and there is
therefore no per-key host dump to reconcile `kick_ret_td` against
directly (unlike the module's other nine PBP-derived keys, all of which
Sleeper does publish under the same name).

Weeks 1, 5 and 11 (the other three fixture weeks) have zero real
kickoff-return-TD plays in the 2025 PBP release — a genuine zero, pinned
by `test_kick_ret_td_is_a_real_zero_on_weeks_with_no_kickoff_return`.

## Fixtures regenerated, not hand-authored

`tests/nfl_data/fixtures/pbp_2025_wk{1,5,11,14}_slice.csv` were
regenerated from the live 2025 nflverse PBP release with two new
columns (`kickoff_returner_player_id`, `own_kickoff_recovery_td`) added
to the required-column set. Every pre-existing column's values were
verified byte-for-byte identical to the previously-committed fixtures
before the new columns were appended (2738/2454/2575/2422 rows, 0
mismatches across all four weeks on every shared column) — this is a
genuine append, not a re-derivation that could have silently drifted
the existing reconciliation.

## Confirmed unchanged

`kr_yd`, `pr_yd`, `st_td`, blocked-kick scoring (`idp_blk_kick`), SAF
normalization (`POSITION_ALIASES`), and individual-ST-vs-DST separation
(`_NOT_APPLICABLE_KEYS`/`_NOT_APPLICABLE_PREFIXES`) are all unmodified
by this unit and remain correctly scored/separated per #915's prior
repair — re-verified by the full `tests/nfl_data/` suite passing
unmodified alongside the new tests.

## L2 measurements

**(a) Current league point delta — provably 0, not merely measured 0.**
`audit_scoring_settings` skips zero-rated keys entirely
(`src/nfl_data/scoring_coverage.py`). Direct key lookup against both
live league scoring-card evidence fixtures
(`docs/master-site-audit/evidence/W18/sleeper_league_1312006700437352448.json`
= `dynasty_main`,
`docs/master-site-audit/evidence/W18/sleeper_league_dynasty_new.json` =
`dynasty_new`) confirms all four disputed keys are absent/zero on both.
The point delta on both live leagues today is **0** — this repair is
correctness/future-proofing, not a change to any currently-published
number. Pinned by
`test_neither_live_league_configures_the_four_disputed_keys`.

**(b) Fully-configured-fixture delta — nonzero, proves the repair
works.** A synthetic card (`SYNTHETIC_RETURN_TD_CARD`, all four keys at
6.0/event — a configuration neither live league has) run through
`compute_weekly_points`: a kickoff-return-TD instance and a
punt-return-TD instance each score exactly `6.0` post-fix, `0.0`
pre-fix (see the mutation transcript below). Pinned by
`test_kick_ret_td_and_punt_ret_td_move_a_real_players_total`.

## Mutation proof (RED-before / GREEN-after, transcript)

**`punt_ret_td`** — removing the `_SIMPLE_KEYS` entry:

```
FAILED tests/nfl_data/test_individual_special_teams.py::test_return_td_categories_are_scored[punt_ret_td]
FAILED tests/nfl_data/test_individual_special_teams.py::test_kick_ret_td_and_punt_ret_td_move_a_real_players_total
  assert 0.0 == 6.0
FAILED tests/nfl_data/test_scoring_coverage.py::test_punt_ret_td_is_a_bare_weekly_feed_key
  assert <Coverage.GAP> is <Coverage.SCORED>
3 failed, 50 deselected
```
Restored → 53 passed.

**`kick_ret_td`** — removing the PBP predicate block in `_iter_plays`:

```
FAILED tests/nfl_data/test_pbp_weekly.py::test_kick_ret_td_reconciles_against_combined_st_td
  assert 0.0 == 1.0
FAILED tests/nfl_data/test_pbp_weekly.py::test_kick_ret_td_fires_on_a_kickoff_return_touchdown
  KeyError: '00-kr'
2 failed, 160 passed
```
Restored → 162 passed.

## V1-49 report

- **V1-49 REPRODUCED**: YES (the #1020 finding — four unscored keys —
  reproduced exactly as described; #1027's finding also independently
  reconfirmed, unrelated residual).
- **Exact supported semantics**: table above.
- **Exact head**: `origin/main` `54a70883e71e1c68c12099226aca6e4baeef8db6`.
- **Mutation**: two mutations, both RED-before/GREEN-after, transcript
  above.
- **Current-league point delta**: 0 (structural, both live leagues).
- **Configured-fixture point delta**: +6.0 per scored event (exact,
  synthetic fixture).
- **Remaining production proof**: unchanged from #1027 — the
  `host_native_scoring` promotion path is `PRODUCTION_ONLY`, 4 of 10
  promotion-gate items open (`docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md`
  §4). This repair does not touch or depend on that flag.
- **CLOSURE_READY**: YES for this unit's scope (the four disputed
  keys). V1-49 as a whole stays gated on the unrelated
  `host_native_scoring` production proof, which this unit does not
  authorize or attempt to close.

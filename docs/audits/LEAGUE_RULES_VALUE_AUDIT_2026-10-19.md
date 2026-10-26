# League-specific scoring, roster and valuation audit — 2026-10-19 (live rules reconciled 2026-10-26)

**Status: PARTIAL EVIDENCE AUDIT — issue #1842 checkbox 1 (live rules reconciliation) is now evidenced; checkboxes 2–9 remain open. NOT a complete site-wide certification.**  
**League:** `dynasty_main` / Sleeper `1312006700437352448` (second league `dynasty_new` / `1320092771247222784` checked for isolation only).  
**Scope:** Calculator repository only. Main-branch source reviewed 2026-10-19; live Sleeper rules, production `/api/leagues` and the export archive reconciled 2026-10-26.

**What the 2026-10-26 reconciliation did and did not establish**

| Established (evidence in §6) | Still NOT established |
|---|---|
| A live `GET /v1/league/1312006700437352448` at 2026-10-26T08:25:58Z has scoring fingerprint `sf1:9e51824690d091f9` and roster fingerprint `rf1:10f897578eea2fe4` — byte-for-byte the IDP-accuracy Lane A pin taken 2026-10-25T20:15:28Z (PR #1931). | That production's **runtime** scoring snapshot (`data/leagues/scoring_<id>.json`, `meta.scoringFingerprint`) is fresh: `/api/data` needs login and was not used. Only behavioural evidence exists (§6.5). |
| The live **scoring card has drifted from the repo's archived 2026-07-26 snapshot on 21 rate keys** (plus 7 keys added at 0.0). It changed in a one-day window, 2026-08-18 → 2026-08-19, i.e. **before any 2026 scored week**. | The exact moment of change. Sleeper publishes no settings history; the export archive brackets it to one day. |
| Roster shape (12 teams, 58 slots, 21 starters, 37 BN, no taxi/IR, best ball) agrees across live Sleeper, `config/leagues/registry.json`, the archived snapshot and production `/api/leagues` for `dynasty_main`. | Whether `dynasty_new`'s registry `rosterSize` 27 vs live 24 slots is a registry error or a different counting convention (owner decision). |

## 1. Actual recorded league shape

`config/leagues/registry.json` and the live Sleeper object (evidence `docs/audits/evidence/league_rules_dynasty_main_2026-10-26.json`) agree: a 12-team best-ball league, 58 rostered slots, zero taxi, 21 starters: QB 1, RB 2, WR 3, TE 2, FLEX 2, SUPER_FLEX 1, K 1, DL 3, LB 3, DB 3, plus 37 bench. The host settings record 7 playoff teams beginning week 15, 6 rookie draft rounds, $100 FAAB (`waiver_type` 2), trade deadline week 13. **Do not substitute previously discussed League Tycoon / 10-IDP proposals.**

Scoring is not ordinary PPR. Live card (148 keys; 2026-10-26): `pass_yd=.04`, `pass_td=6`, `pass_int=-4`, `pass_cmp=.37`, `pass_inc=-.67`, `rush_att=.01`, `bonus_fd_qb=.4`, `bonus_fd_rb/wr/te=1`, `rec=.1` plus reception-**length** bands (`rec_0_4` .25, `rec_5_9` .5, `rec_10_19` .75, `rec_20_29` 1.0, `rec_30_39` 1.25, `rec_40p` 2.0 — the band is the length of that catch, on top of the flat rate and `rec_yd=.1`), `bonus_rec_wr=.02`, `idp_tkl_solo=1.33`, `idp_tkl_ast=.8`, `idp_tkl_loss=4.24`, `idp_sack=2.92`, `idp_qb_hit=2.12`, `idp_pass_def=5.3`, `kr_yd/pr_yd=1/30`. Kicking pays `fgm_yds=.07` rather than a flat successful-FG base. **The numbers in the pre-reconciliation draft of this section (`rec=.08`, `pass_cmp=.15`, `bonus_fd_qb=.67`, `idp_tkl_loss=4.25`, …) were the archived 2026-07-26 values and are no longer the league's rules** — see §6.1.

### Tight end is two separate questions
The live card has `bonus_rec_te=0` and `bonus_fd_te=1` (identical to WR and RB) while requiring **two TE starters**. It is inaccurate to infer a scoring premium solely from the two mandatory TE slots. `src/league_intel/te_premium.py` separates source-format normalization from structural demand and reports a TE++ target basis for two required TEs. Validate whether that basis aligns with actual outcomes and avoid applying another lift to a TE++ normalized source. **The registry's `superflex_tep15_ppr1` label is factually wrong for this league on both counts it names** (no TE-premium scoring; reception pay is `.10` flat plus length bands, not "ppr1") — it is a model/config label and, per CLAUDE.md §4.10, may not decide a factual scoring question. The only position-specific reception bonus on the live card is `bonus_rec_wr=.02` (a tiny WR premium).

## 2. Source-to-consumer trace, observed from code

| Layer | Verified path | What is demonstrably implemented | Evidence gap / risk |
|---|---|---|---|
| League registry | `src/api/league_registry.py`, `config/leagues/registry.json` | Default/secondary league mapping; roster settings and league key. Production `/api/leagues` is byte-equal to the registry's `rosterSettings`, `scoringProfile`, `idpEnabled`, `bestBall` for both leagues (§6.3). | The registry carries **no scoring card**, so a registry "MATCH" says nothing about scoring. `scoringProfile` is a label, not a computation. `dynasty_new` `rosterSize` 27 disagrees with its live slot list (24). |
| Full-fidelity config | `src/league_intel/config.py` and dated snapshot | Validates Sleeper scoring/slots; has `refresh_snapshot` drift detection. | `load_canonical_config()` returns the **newest dated file** in `config/league_intel/` — still the 2026-07-26, 141-key card, now 21 rate keys behind the live league. `refresh_snapshot` has **no scheduled caller** (`.github/`, `deploy/`, `scripts/`, `src/` and `server.py` were searched; `docs/league-intelligence/STATUS.md` describes it as a manual refresh path). Its only runtime consumer is `consensus_edge/scoring_fit.py` (deliberately snapshot-based "so the number can be replayed"); it stamps `scoringVersion = 2026-07-26` but does not compare against the live fingerprint or fail closed. See the propagation matrix (Part 2 of #1842) for the route-level consequence. |
| Scoring engine | `src/league_intel/scorer.py`; `src/scoring/sleeper_ingest.py` | Exact-score dot product and aliases; goldens 1,415/1,415 archived 2025 player-weeks within .011 under 2025 rules. **2026 host-awarded reconciliation now exists on PR #1931 (Lane A, not yet merged):** the host-native path reproduces Sleeper's `players_points` on 3,710/3,710 scored player-weeks of 2026 weeks 1–6 within 0.01 under the live 148-key card; the nflverse path (`src.bdvm.actuals`) reproduces 2,832/3,095 and has four attributed scorer defects (IDPA-DEFECT-01..04). | #1931 is an open PR, so this is evidence about a branch, not about `main`. It verifies arithmetic on realized weeks only (in-sample, 6 weeks). Because the card changed 2026-08-18/19, every scored 2026 week was scored under the live card; the archived July card never applied to a scored week. |
| League scoring-fit | `src/league_intel/scoring_fit.py` | Historical re-score-based **positional** IDP fit; corrections documented for `idp_qb_hit` alias. | Per-player adjustment from sparse historical IDP event rates was rejected as noisy; update with robust projections only if validated. Inputs come from the stale snapshot above. |
| Structural scarcity | `src/league_intel/replacement.py`, `src/ros/lineup.py` | Exact lineup assignment and replacement tiers with FLEX/SFLEX; recorded 2025 TE FLEX share 10.4% vs 0% from mean-index route. Slot list is identical on every source (§6.3). | Mean `rosValue` masks weekly spike participation in best ball. Current bench/roster availability varies with identity freshness. |
| Canonical value | `src/api/data_contract.py::_compute_unified_rankings` | Weighted source rankings → canonical `rankDerivedValue`; Superflex and TE++ source-basis alignment are documented. | Not equivalent to exact-league intrinsic projected production. Audit all source basis and second-opinion fallbacks. |
| Optional adjusted bundle | `src/league_intel/values.py`, `publish.py` | Stores `marketValue`, `consensusValue`, `leagueAdjustedDynastyValue` independently. | Presence of a bundle value **does not** establish canonical adoption. |
| Canonical promotion boundary | `frontend/lib/valuation-mode.js`, `server.py::_valuation_scoped_contract` | The 2026-08-14 league lens was withdrawn: frontend returns market, backend ignores requested `leagueAdjusted` and returns canonical contract. | Preserve this until a separately validated replacement is authorized. |
| Seasonal projected points | `src/ros/projection_observations.py`, `projection_ensemble.py` | Raw stat lines can be re-scored through caller league rules. Full-season ensemble built from registered provider families. | Provider coverage uneven; multi-family seasonal projection does NOT automatically modify dynasty canonical value. |
| Best-ball trade utility | `src/roster_intel/best_ball_utility.py` | Samples weekly outcomes and re-optimizes lineup per simulated week; can use league-scored ensemble. | Its own assumptions state independent player draws; missing/uncertain availability and full-season-rate-as-weekly-proxy may bias value. |
| Trade engine contract | `server.py::_valuation_scoped_contract` | Multiple trade / waiver endpoints share a declared canonical-value boundary. | Need per-endpoint sensitivity tests of rules, pick valuations, timing, league-key scope. |

## 3. League configuration propagation matrix — now a separate record

The route-by-route matrix (owner read, correctness against the "scoring controls rankings, league key controls context" split, stale-snapshot behaviour, pinning test) and its metamorphic tests are delivered under #1842 checkboxes 3–4 on branch `claude/li1842-propagation-matrix`: `docs/audits/LEAGUE_CONFIG_PROPAGATION_MATRIX_2026-10-26.md` and `tests/league_intel/test_league_config_metamorphic.py`. The family-level queue that stood here is superseded by it; the rule dimensions to vary stay as listed there. Until that PR lands, treat the table that used to be here as a **work queue, not a PASS**.

## 4. Confirmed pitfalls to address, without premature behavior changes

1. ~~Live source of truth unavailable in this audit run.~~ **Answered 2026-10-26** (§6). Remaining limit: a live GET proves Sleeper's rules at that instant only; production's own runtime copy was not observed.
2. **Canonical dynasty value ≠ projection or exact league utility.** Production withdrawal of the league-adjusted lens is documented in `docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md`. Do not silently revive it.
3. **Best-ball demand requires full weekly distributions.** Mean-based flex allocation misses spikes; historical weekly replay already documents this.
4. **Source census ≠ functioning production fetch.** `config/projections/source_capability_census.json` distinguishes LIVE, IMPLEMENTED_FLAG_OFF, GREENFIELD and RANKINGS_ONLY. Check runtime snapshot freshness and access rights.
5. **No unmeasured 0–9999 multiplication.** Prior method used `rosValue` (rank index) as if it were physical points, omitted roster size/team count mathematically, and risked SF/TE double counting. It was rejected on 2026-08-14.
6. **Past documents are not deploy proof.** Several docs describe work awaiting merge, flags or host verification. Inspect main, active PRs, deployment/version before declaring complete.
7. **Separate player market price, exact league intrinsic forecast, and roster-specific marginal value.** They have different calibration and validation targets.
8. **A committed snapshot is a point in time, not the league.** `config/league_intel/` has been 21 rate keys stale since 2026-08-19 with nothing scheduled to notice. Do not add a newer dated file there as a "fix": `load_canonical_config()` would start serving it to `consensus_edge/scoring_fit.py`, which is a served-behaviour change that needs its own authorization (this audit stores its evidence under `docs/audits/evidence/` precisely so that it changes nothing).
9. **The scoring label is not the scoring.** `superflex_tep15_ppr1` is shared by both live leagues whose cards differ on 34 of 48 shared keys (`sf1:9e51…` vs `sf1:82a5…`). Only `scoring_fingerprint` may decide cross-league reuse.
10. **One archived export (2026-10-21T18:58:55Z) carries `sleeper.leagueSettings.best_ball = 0`** between neighbours that carry 1 (the only changed field). Cause unknown (Sleeper response vs overlay glitch vs a host toggle that was reverted). Nothing in this audit depends on it, but any consumer that reads `leagueSettings.best_ball` (rather than the registry `bestBall`) can flip for one scrape.

## 5. Implementation evidence / next gates

`scripts/audit_league_settings.py` is read-only. It produces a stable SHA-256 `rules_fingerprint` (whole rule-bearing settings block plus slots plus card; transient progress keys excluded), the canonical `scoring_fingerprint_sf1` (imported from `src/league_comparison/sleeper_scoring.py`, never re-implemented), labels `LIVE_SLEEPER_API` vs `EXPLICIT_ARCHIVED_SNAPSHOT`, fails closed on a wrong league or missing card, and `--strict` fails on registry drift. New in this revision: `--baseline <archived snapshot>` produces the key-by-key scoring diff (`SCORING_DRIFT` / `SCORING_MATCH`), because the registry has no card and therefore cannot detect scoring drift on its own. Tests (`tests/league_intel/test_league_settings_fingerprint_audit.py`) pin both the logic and the committed 2026-10-26 evidence, offline.

Reproduce (needs network):

```bash
python scripts/audit_league_settings.py --live --strict \
  --baseline config/league_intel/sleeper_league_snapshot_2026-07-26.json     # exits 1: SCORING_DRIFT
python scripts/audit_league_settings.py --live --league-id 1320092771247222784 --strict   # exits 1: roster_size 27 vs 24
```

**Remaining audit work, not represented as completed here:** 2026 host-awarded score sample for the **offense/K/special-teams** unusual-stacking cases on `main` (Lane A covers the IDP-centred question on #1931), shadow challengers, longitudinal outcome holdouts, and production deploy verification (including a login-gated read of the served `meta.scoringFingerprint`). Log these against the issue/plan before upgrading this report's status.

## 6. Live reconciliation — 2026-10-26 (issue #1842 checkbox 1)

### 6.1 Scoring card: live vs the archived 2026-07-26 snapshot (`sf1:b7ad1575925091f6`, 141 keys → `sf1:9e51824690d091f9`, 148 keys)

120 shared keys unchanged, **21 changed**, 7 added at 0.0 (no rate change), 0 removed.

| key | 2026-07-26 | 2026-10-26 | effect |
|---|---|---|---|
| `rec` | 0.08 | 0.10 | +0.02 per catch |
| `rec_0_4` / `rec_5_9` / `rec_10_19` / `rec_20_29` / `rec_30_39` / `rec_40p` | .17 / .42 / .67 / .92 / 1.17 / 1.92 | .25 / .50 / .75 / 1.00 / 1.25 / 2.00 | +0.08 per catch in every band — with `rec`, **+0.10 per reception at every length** |
| `bonus_rec_wr` | 0.0 | 0.02 | new WR-only per-catch premium |
| `pass_cmp` | 0.15 | 0.37 | completions pay 2.5x |
| `pass_inc` | -0.22 | -0.67 | incompletions cost 3x |
| `pass_yd` | 0.0333 (1/30) | 0.04 (1/25) | +20% per passing yard |
| `bonus_fd_qb` | 0.67 | 0.40 | QB first downs pay less |
| `rush_att` | 0.08 | 0.01 | carries nearly stop paying |
| `idp_tkl_loss` | 4.25 | 4.24 | -0.01 |
| `idp_qb_hit` | 2.13 | 2.12 | -0.01 |
| `idp_ff` | 4.25 | 4.24 | -0.01 |
| `idp_pass_def` / `idp_int` / `idp_safe` / `idp_blk_kick` | 5.32 each | 5.30 each | -0.02 |
| `idp_def_td` | 6.38 | 6.36 | -0.02 |

Keys added at 0.0 (informational, change no rate): `blk_kick_ret_yd`, `bonus_rush_td_qb`, `fgm_50_59`, `idp_tkl`, `pass_td_50p`, `rec_td_50p`, `rush_td_50p`. Unchanged and load-bearing: `pass_td` 6, `pass_int` -4, `bonus_rec_te` 0, `bonus_fd_te/wr/rb` 1, `idp_tkl_solo` 1.33, `idp_tkl_ast` .8, `idp_sack` 2.92, `fgm_yds` .07, `kr_yd`/`pr_yd` 1/30. The IDP shifts are ≤0.02 and probably rounding of the same host intent; the offense shifts (`pass_cmp`, `pass_inc`, `rush_att`, `pass_yd`, `rec`, `bonus_fd_qb`) are large.

### 6.2 When it changed

The export archive stamps the contract's `sleeper.scoringSettings` into every `exports/archive/*.zip` (the archive carries no `meta.scoringFingerprint`; the fingerprint was recomputed from the stored card for all 153 archives, 2026-07-14 → 2026-10-25):

| archives | card | fingerprint |
|---|---|---|
| `dynasty_export_20260714_233659` … `20260818_230211` | 141 keys | `sf1:b7ad1575925091f6` (== the committed 2026-07-26 snapshot) |
| `dynasty_export_20260819_230341` … `20261025_120337` | 148 keys | `sf1:9e51824690d091f9` (== live 2026-10-26) |

So the host edited the card in the ~24 h between 2026-08-18T23:02Z and 2026-08-19T23:03Z (archive timestamps are UTC). At that point `leg` was 1 and `last_scored_leg` null, i.e. before any 2026 game was scored. From then on the repo's snapshot-based consumers disagreed with the league; no alarm exists that would have said so (`refresh_snapshot` is a manual path, §2). Roster format (slot list, team count, taxi/reserve, `type`) and the playoff/draft/waiver settings did not change in that window or since (the archive scan shows one other deviation: the single-sample `best_ball` 1→0→1 of 2026-10-21, pitfall 10).

### 6.3 Roster format and registry — every source, key by key (`dynasty_main`)

| item | live Sleeper 2026-10-26 | `registry.json` | prod `/api/leagues` 2026-10-26 | archived snapshot 2026-07-26 | Lane A pin 2026-10-25 | drift |
|---|---|---|---|---|---|---|
| teams | 12 | 12 | 12 | 12 | 12 | none |
| rosterSize | 58 (= `len(roster_positions)`) | 58 | 58 | 58 | 58 | none |
| starters QB/RB/WR/TE | 1/2/3/2 | 1/2/3/2 | 1/2/3/2 | same | same | none |
| FLEX / SUPER_FLEX (`SFLEX`) | 2 / 1 | 2 / 1 | 2 / 1 | same | same | none |
| K / DL / LB / DB | 1/3/3/3 | 1/3/3/3 | 1/3/3/3 | same | same | none |
| IDP_FLEX | none in slot list | 0 | 0 | none | none | none |
| bench (BN) / starters total | 37 / 21 | 37 / 21 (derived) | derived | same | same | none |
| taxi / reserve | 0 / 0 | taxi 0 | taxi 0 | 0 / 0 | 0 / 0 | none |
| best ball | 1 | `bestBall` true | true | 1 | 1 | none |
| `flexEligible` / `sflexEligible` | (Sleeper standard) | RB,WR,TE / QB,RB,WR,TE | identical | – | – | none |
| playoff teams / start week / draft rounds / FAAB | 7 / 15 / 6 / $100 | not carried | not carried | 7 / 15 / 6 / 100 | – | none |
| `scoringProfile` | – | `superflex_tep15_ppr1` | `superflex_tep15_ppr1` | – | label only | **label ≠ fact** (§1) |
| scoring fingerprint | `sf1:9e51824690d091f9` | not carried | not served publicly | `sf1:b7ad1575925091f6` | `sf1:9e51824690d091f9` | **live ≠ snapshot** (§6.1) |
| roster fingerprint | `rf1:10f897578eea2fe4` | – | – | `rf1:10f897578eea2fe4` | `rf1:10f897578eea2fe4` | none |
| whole-rules fingerprint (`league-rules-sha256-v1`) | `aeed26b8…c2d138` | – | – | differs (§6.4) | – | n/a |

`scripts/audit_league_settings.py --live --strict` against the registry exits 0 (`MATCH`) for `dynasty_main` — which is correct but, because the registry has no card, does **not** cover scoring.

`dynasty_new` (live `sf1:82a5f8ef2bfdb098`, 48 keys, unchanged since its 2026-08-25 snapshot): starters, taxi 3, reserve 3, best ball 0, teams 10 all agree. **One drift:** registry `rosterSize` **27** vs live `roster_positions` **24** (BN 14; the 2026-08-25 snapshot had BN 17 = 27 slots). Production `/api/leagues` serves the same 27. Whether Sleeper's "roster size" for this league should count taxi/reserve on top of the 24 is an owner/config question; the audit script's convention (`len(roster_positions)` excluding IR/TAXI/RESERVE) and the registry's `dynasty_main` convention both give 24 today.

### 6.4 Non-scoring host settings that differ from the 2026-07-26 snapshot

`commissioner_direct_invite` 1 → 0, `disable_adds` 1 → 0 (the July snapshot predates the season), `daily_waivers_days` 10922 → 5463 (waiver-day bitmask). Progress keys `leg` 1 → 7, `last_scored_leg` null → 6, `last_report` null → 6 are excluded from the fingerprint by design. These alter `rules_fingerprint` (it hashes the whole settings block) but not `sf1`; use `sf1` for scoring identity and `rules_fingerprint` only for "did anything the host controls change".

### 6.5 Production observation (public endpoints only)

* `/api/leagues` (2026-10-26T08:27Z): equal to the registry for both leagues (§6.3). No Sleeper id is in this payload.
* `/api/status`: running commit `3ff33ee2…`, contract health `ok` (`degraded`: two withheld source votes), `leagues[]` lists both keys and — contrary to the CLAUDE.md "no endpoint exposes raw Sleeper IDs" line — each `sleeperLeagueId` (public Sleeper ids, not credentials; recorded as an invariant deviation).
* `/api/draft-capital?leagueKey=dynasty_new` returns `rookieSource: "none"` while `dynasty_main` returns `ours_filtered` / a computed rookie ladder. That is exactly what the scoring-identity gate (W18-F001) is specified to do when the two leagues' fingerprints differ or are unproven, so production's gate is behaving consistently with `sf1:9e51…` ≠ `sf1:82a5…`. It is **behavioural evidence, not a read of the stamped fingerprint**: an absent or stale `dynasty_new` snapshot would produce the same refusal.

### 6.6 Artifacts

* `docs/audits/evidence/league_rules_dynasty_main_2026-10-26.json`, `…_dynasty_new_…json` — rules only (scoring card, slot list, rule-bearing settings, fingerprints, fetch time, raw-response sha256); no manager, team or user identifiers. Passing the first to `--snapshot` reproduces `rules_fingerprint` `aeed26b8…`.
* `config/league_intel/` is **deliberately untouched** (pitfall 8).

## 7. Owner-approved precedence

Preserve already approved source voting, value adjustment, league-specific strategy and parallel-development policy. Do not overwrite active PRs. League Tycoon contract conversion remains postponed. Source ingestion is separate from voting activation; seasonal projection models do not become dynasty voter sources. Model promotion needs outcome evidence, appropriate review and owner authorization.

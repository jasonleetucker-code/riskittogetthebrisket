# B6 / W18-F001 — where the factual scoring identity lives

Written during the RED phase, before any production repair, to answer the
six architectural questions the owner required to be resolved *while* the
REDs were written rather than discovered during implementation.

Every claim below is verified against HEAD `46fde233f`
(B6 baseline `8f92c05e8` + the B5 identity-regression evidence commit).

---

## 0. What the code actually does today (verified, not recalled)

`leagues_share_scoring()` (`src/api/league_registry.py:492-507`) is the
documented single owner of "may these two leagues share scoring-dependent
rankings?". Its body is one line of label equality.

**It has zero production callers.** A repository-wide search finds it in
its own definition, in `tests/api/test_league_routing.py:740-743`, and in
audit documents — nowhere else. The question is actually decided by
**five** inline comparisons in `server.py`:

| line | endpoint | shape |
|---|---|---|
| 3303 | `GET /api/data` | `if loaded_profile and loaded_profile != league_cfg.scoring_profile` |
| 4044 | `POST /api/rankings/overrides` | same |
| 11254 | `GET /api/terminal` | same |
| 11479 | `POST /api/trade/simulate` | same |
| 8930 | `GET /api/draft-capital` (rookie pool) | `get_scoring_profile(loaded) == get_scoring_profile(requested)` |

The first four share the fail-open shape the finding names: the
incompatibility check is *gated on the loaded identity being truthy*, so a
contract carrying no `meta.scoringProfile` is treated as compatible with
every league. The fifth is label equality without the fail-open guard.

Two consequences for the repair:

* Putting the fingerprint into `leagues_share_scoring` alone would change
  **nothing observable**. The repair must also route all five sites
  through that one owner — "one concept, one canonical owner" is not
  satisfied by a helper nobody calls.
* `tests/conftest.py` points `LEAGUE_REGISTRY_PATH` at a synthetic
  registry, so `leagues_share_scoring("dynasty_main", "dynasty_new")` is
  `False` under test and `True` in production (W24-F006). The B6 REDs
  therefore patch `get_league_by_key` directly and never depend on the
  shipped registry file.

---

## Q1 — Where is the factual fingerprint generated?

**`src/league_comparison/sleeper_scoring.py::scoring_fingerprint(scoring) -> str | None`.**

A pure function of a scoring-settings mapping. That module already owns
"read a Sleeper league's scoring card" and already carries a hash of one;
adding a third module for the same concept is the duplication this phase
exists to remove.

It is a **new function, not a promotion of `_scoring_hash`**
(`sleeper_scoring.py:56-58`). `_scoring_hash` is
`sha1(json.dumps(scoring, sort_keys=True, default=str))[:12]`. It gets key
ordering right and three things wrong for a compatibility identity:

* `1` and `1.0` serialize differently — the same rule, two hashes;
* a missing key differs from an explicit `0.0`, though Sleeper scores an
  absent rule as zero;
* `default=str` silently absorbs any non-scoring value that happens to be
  in the mapping.

Each of those manufactures **false incompatibility**, which is the same
class of error as the label with the sign flipped. `_scoring_hash` keeps
its four existing consumers unchanged
(`src/league_comparison/service.py:406-407,526,532` — the league-comparison
display, where "did anything at all change" is the right question).

Normalization rules, each pinned by a test in
`tests/api/test_scoring_compatibility.py::TestFingerprintStability`:

| rule | test |
|---|---|
| key order is irrelevant | `test_key_order_is_irrelevant` |
| numeric form is irrelevant (`1` = `1.0` = `1.00`) | `test_numeric_form_is_irrelevant` |
| an absent rule equals an explicit `0.0` | `test_absent_rule_equals_explicit_zero` |
| non-scoring metadata is excluded | `test_irrelevant_metadata_is_excluded` |
| a material scoring difference changes it | `test_a_material_scoring_difference_changes_it` |
| `None` in → `None` out; missing is never zero | `test_missing_input_is_not_a_fingerprint` |
| deterministic across calls | `test_it_is_deterministic_across_calls` |

**What belongs in it:** the league's scoring settings and nothing else.
Not league name, season, roster size, team count or draft config — those
do not change what a player is worth, and hashing a whole league object
would make two identically-scored leagues incompatible for irrelevant
reasons.

---

## Q1a — How long does a snapshot stay proof? (owner review, gap 1)

A snapshot proves **"this league had these rules when the fetch last
succeeded"** — not "this league still has these rules". `refresh_scoring_snapshot`
deliberately keeps the previous card when a refresh fails, which is right
(a transient Sleeper blip should not destroy evidence), but left unbounded
that turns into W18-F001 reached through time: change a league's scoring,
have every later refresh fail, and an indefinitely old card keeps
authorizing cross-league ranking reuse.

**The budget is derived, not chosen.** The snapshot is written by the
post-scrape warm pass, so it is a scrape-cadence artifact, and this repo
already has exactly one staleness budget for those — stated twice,
identically:

* `scheduled-refresh.yml` runs `42 */2 * * *`, and `SCRAPE_INTERVAL_HOURS`
  is 2;
* `server.py` calls the loaded contract stale at
  `SCRAPE_INTERVAL_HOURS * 3` → **6 h**;
* `data_contract._SOURCE_MAX_AGE_HOURS` gives **6 h** to every source on
  that cadence (`ktc`, `ktcSfTep`, `idpTradeCalc`, `fantasyCalc`,
  `otcffbSf`, …), with the docstring reasoning spelled out per source.

`SCORING_SNAPSHOT_MAX_AGE_HOURS = 6` therefore follows the existing
convention rather than inventing a number, and
`test_the_budget_matches_the_repo_convention` pins it against both
precedents so it cannot drift away from what derived it.

**Three states, in the vocabulary the repo already uses** for source
freshness (`_build_source_timestamps` emits `fresh` / `stale` / `missing`):

| state | meaning | may prove compatibility? | card readable? |
|---|---|---|---|
| `fresh` | fetched within the budget, for this season | **yes** | yes |
| `stale` | too old, undated, or from another season | no | **yes** |
| `missing` | no snapshot, or unusable content | no | no |

Stale is deliberately not deletion: `scoring_settings_for_league` still
returns the card for diagnostics, and only `scoring_fingerprint_for_league`
— the function whose answer authorizes reuse — returns `None`.

**Season is a second, independent boundary.** Sleeper leagues chain year
to year under new ids, so a registry entry left pointing at last season's
league would keep fetching a perfectly *fresh* card describing the wrong
season. Age cannot catch that; comparing the snapshot's recorded season
against `nfl_projection_season()` can.

**Season must be VERIFIED, not merely un-contradicted** (owner re-review).
The first cut wrote `if season:` around the comparison and swallowed
resolver errors with `except: pass`, so two cases reached `fresh` without
any season ever being checked: a snapshot with no recorded season, and a
current-season resolver that could not answer. Both are "we do not know
which season this card describes", and an unknown may not be treated as a
match. They now return **stale** — the same state the undated-card branch
three lines above already uses, and for the same reason: the card is
present and readable, it simply cannot prove it is current. No fourth
state was needed; the existing `fresh` / `stale` / `missing` vocabulary
already had the right slot.

Safe because the writer supplies one: `refresh_scoring_snapshot` passes
`season=info.season` from the Sleeper league object, and both live
snapshots carry `"2026"`. `test_the_real_snapshot_writer_records_a_season`
pins that, so the strictness cannot silently turn every card
permanently stale.

**Same-league requests are unaffected**, which is what bounds the blast
radius: `_scoring_identity_error` short-circuits when the loaded contract's
league key equals the requested one, so the default league keeps serving
normally no matter how stale any cross-league evidence gets.

## Q2 — Where is it stored?

Three places, with one authority each. This is deliberately *not* "pick
one".

**(a) Never hand-authored in `config/leagues/registry.json`.** The
registry keeps `scoringProfile` exactly as it is — a config/model label
with real consumers that are not compatibility
(`src/bdvm/service.py:289`, `src/api/gameplan.py` bundle inputs,
`src/api/bdvm_api.py:203`, `src/draft/context.py:150`). Adding a
hand-typed `scoringFingerprint` field beside it would reproduce the exact
defect one field to the right.

**(b) Per-league card, cached on disk, refreshed from the host.** The
factual card for a league that is *not* the loaded one has exactly one
truthful source: Sleeper. It is read through
`fetch_league_scoring(sleeper_league_id)`, which already exists and
already has a 1 h in-process TTL
(`sleeper_scoring.py:29,69`), and persisted under `data/leagues/` so a
cold process and an offline moment do not turn into a fail-closed outage
on every cross-league request. `data/` is gitignored, matching every
other host-derived cache in this repo.

Refresh has a natural existing home: `server.py:2110-2117` already warms
the Sleeper overlay **for every active league** after each scrape. The
scoring card is fetched from the same league object.

**(c) The loaded contract carries its own, derived from itself.**
`meta.scoringFingerprint`, stamped beside `meta.scoringProfile` at
`server.py:2101-2107`, computed from `contract["sleeper"]["scoringSettings"]`
— the card the scrape actually used. See Q3.

---

## Q3 — How does a loaded contract prove which scoring its rankings were built under?

By carrying a fingerprint **derived from data inside the contract**, not
copied from the registry.

`meta.scoringProfile` is stamped today from
`get_default_league().scoring_profile` (`server.py:2106`) — a label copied
from config, which proves only that config said so. Copying a
registry-side fingerprint the same way would launder the label into
something that merely *looks* factual.

Instead `meta.scoringFingerprint` is computed from
`contract["sleeper"]["scoringSettings"]`, which the scrape fetched from
the host for the league it built. That makes the stamp **independently
recomputable by any reader of the contract**: a consumer that doubts it
can hash the contract's own scoring block and compare. A stamp that can
be checked against the artifact it describes is a proof; a stamp copied
from a second file is a claim.

Corollary the repair must respect: if `sleeper.scoringSettings` is absent
or empty on a build, the contract gets **no** fingerprint rather than a
hash of `{}`. Missing is never zero.

### Q3a — the stamp must agree with the card (owner review, gap 3)

The first implementation *preferred* the stamp and never compared it with
the card, which quietly gave up the property that justified having a
contract identity at all. A stamp is a **cache of** the card, so the
resolution order is now explicit rather than emergent:

| card | stamp | result |
|---|---|---|
| present | agrees | that fingerprint |
| present | absent | recompute — the migration path |
| present | **disagrees** | **`None`**, and a warning naming both |
| present | different `sf*` version prefix | `None` — normalizations are not comparable |
| **absent** | present | **`None`** |

The last row is a decision, not a fallthrough. A stamp with nothing to
check it against is unverifiable, and unverifiable fails closed. The
documented migration policy never leaned on that branch: it leaned on the
card, which every real contract carries — the live board's is 141 keys.

Hashing 141 keys per request costs ~85 µs, so the comparison is memoized
on `(id(sleeper), id(card), len(card), stamp)` in a single-entry memo.
That is an accelerator only: a miss recomputes and the comparison it
accelerates is unchanged, and every scrape swaps the contract object so
the key changes with it.

---

## Q4 — What happens to older contracts that lack the fingerprint?

They are **unverifiable**, and unverifiable fails closed.

**Measured correction (2026-08-12), after implementation.** This section
originally predicted a one-refresh-cycle degradation for every existing
contract. That over-stated it, because of the Q3 fallback: the live
board on disk (`exports/latest/dynasty_data_2026-08-12.json`) stamps
neither `meta.scoringProfile` nor `meta.leagueKey`, yet its own
`sleeper.scoringSettings` block (141 keys) derives
`sf1:b7ad1575925091f6` — the correct dynasty_main identity. A contract
carrying its scoring card is therefore identified **immediately**, with
no rebuild. Only a contract with no sleeper block at all is genuinely
unverifiable.

What *does* need a refresh is the other side: a league with no
`data/leagues/scoring_*.json` snapshot yet. `scripts/fetch_league_scoring.py`
covers that in one command on a fresh deploy, and the post-scrape warm
pass covers it thereafter.

The blast radius is narrow and worth stating exactly, because "fail
closed" sounds larger than it is here:

* **The loaded league's own requests are unaffected.** Every one of the
  five sites short-circuits on `loaded_league == league_cfg.key` (or is
  only reached when the leagues differ). A contract without a fingerprint
  still serves its own league normally.
* **Only cross-league requests degrade**, and to the response that already
  exists for this case: `503 data_not_ready` with a message naming the
  reason. `/api/terminal` and `/api/trade/simulate` already 503 on this
  branch for other reasons; `/api/data` and `/api/rankings/overrides`
  gain it.
* **It self-heals in one scrape cycle.** `scheduled-refresh.yml` runs
  every 2 h, and both the stamp and the snapshot are refreshed on that
  cadence, so no migration step or backfill is required — only
  `scripts/fetch_league_scoring.py` on a cold deploy that has not
  scraped yet.

What must *not* happen: treating "no fingerprint" as "compatible", which
is the live defect (`if loaded_profile and ...`), or synthesising one from
the registry label, which is the same defect wearing the repair's name.

---

## Q5 — Should migration / backward compatibility be fail-closed until a fresh contract is built?

**Yes.**

The comment at `server.py:3299-3302` states the current rule outright:
*"Missing loaded_profile means we're running a contract built before this
refactor; treat it as if profiles match."* That is a backward-compatibility
exemption, and it is precisely the finding. Re-granting it for the new
field would carry the bug across the repair with a deprecation window
attached.

The asymmetry decides it. Failing closed costs cross-league requests a
`503` for at most one refresh cycle. Failing open costs one league's board
served verbatim under another league's name, with no field on the response
saying so — which is what the two live leagues do today.

---

## Q6 — Do any current cache keys need the factual fingerprint?

**Audited; no.** Every league-sensitive cache in the request path is
already keyed by something strictly finer than the scoring fingerprint —
the league itself:

| cache | key | verdict |
|---|---|---|
| `src/api/gameplan.py::_BUNDLE_CACHE` | `league_key` + `inputs.source_stamp` (`gameplan.py:597,609`) | safe. `scoring_profile` is a build *input*, not part of the key |
| `src/api/gameplan.py::_TEAM_CACHE` | `f"{league_key}\x00…"` (`:580`) | safe |
| `src/api/bdvm_api.py::_values_cache` | tuple including `league_key` (`bdvm_api.py:183-196`) | safe |
| `src/api/bdvm_api.py::_actuals_cache` | `(nfl_season, day)` (`:139`) | safe — NFL-wide, not league-scoped |
| `src/api/sleeper_overlay.py::_CACHE` / `_TEAMS_CACHE` | `sleeper_league_id` (`:1336,1422`) | safe |
| frontend `useTerminal` | `{ownerId, name, windowDays, leagueKey, valuationMode}` (`useTerminal.js:52`) | safe |
| `latest_contract_data` / `latest_data_bytes` | single-valued (the one loaded contract) | not a key problem — the **gate** is what protects it, which is the repair |

Adding the fingerprint to any of these would be redundant, and redundant
key material is not free: it invalidates caches on scoring edits that do
not change the cached artifact.

The rule this leaves for new code, recorded here because there is no
current violation to point at: **a cache may be keyed by `leagueKey`, or
by the factual scoring fingerprint — never by `scoringProfile`.** The
label is not an identity, which is the whole of W18-F001.

---

## Measured outcome on the shipped configuration

`b6_validate.py` in this directory boots the real app against the real
`config/leagues/registry.json` and the live board, with no fixtures.
Output pinned in `b6-validation.json`:

| | dynasty_main | dynasty_new |
|---|---|---|
| `scoringProfile` | `superflex_tep15_ppr1` | `superflex_tep15_ppr1` |
| `scoringFingerprint` | `sf1:b7ad1575925091f6` | `sf1:82a5f8ef2bfdb098` |

`labelsAgree: true`, `fingerprintsAgree: false` — the defect, caught.

Endpoint outcomes with dynasty_main's board loaded:

| endpoint | dynasty_main | dynasty_new |
|---|---|---|
| `/api/data` | 200, `sleeperDataReady: true` | **503** `data_not_ready` |
| `/api/terminal` | 200 | **503** `data_not_ready` |
| `/api/draft-capital` | 200 | 200 (see below) |

`/api/draft-capital` deliberately stays 200 for a foreign league — its
Sleeper-derived fallback builds that league's own pick board and does not
need the contract (CLAUDE.md, D-2). What changed is narrower and
measured in isolated processes (a same-process A/B is invalidated by the
route's own cache):

| | old gate (labels matched) | new gate |
|---|---|---|
| `rookieSource` | `contract` | `none` |
| rookie rows priced | 40 | 0 |
| picks emitted | 80 | 80 |

So dynasty_new was being shown 40 rookies priced under 0.08-PPR /
6-point-TD scoring on a full-PPR / 4-point-TD board. They are now
withheld while the league's real pick board is untouched — the same
"unpriced rather than invented" posture `isUnpriced` and
`assetsUnpricedByBoard` already take elsewhere.

### Readiness requires a COMPLETE config (owner review, gap 2)

The first implementation gated readiness on a truthy `scoringSettings`
alone. But `_fetch_league_config` built its block with
`list(info.get("roster_positions") or [])` and
`dict(info.get("settings") or {})`, so a partial Sleeper response yielded
valid scoring beside `rosterPositions: []` and `leagueSettings: {}` — and
that published as ready.

What "complete" means was traced to the consumers, not assumed:

| field | requirement | why — the consumer |
|---|---|---|
| `scoringSettings` | non-empty mapping | BDVM raises without it; it is the whole point |
| `rosterPositions` | **non-empty** list | `bdvm/league_config.py` gates on `if roster_positions and scoring:`, so `[]` falls through to the registry — i.e. it means *missing*. And `frontend/lib/starter-slots.js` ranks live `rosterPositions` **above** the registry, so an empty live list beats correct registry settings and yields an empty lineup |
| `leagueSettings` | present **and** `num_teams > 1` | the same builder reads `league_settings["num_teams"]` and raises `LeagueConfigError` at `teams <= 1` |

So there is no legitimate empty-but-present case here: every Sleeper
league has lineup slots and a team count, and their absence means the
fetch did not produce them. `league_config_is_complete` is the one place
that decides, `_fetch_league_config` returns `None` (with a warning) on a
partial answer rather than passing skeletons downstream, and the merge
leaves every league-specific field absent when it is not satisfied.

### Cost of the gate

Measured on a **quiescent** process — worth stating, because an earlier
measurement of this gate was taken while `public-league-warmup` was doing
network I/O and `Path.stat()` alone read 882 µs under that contention. The
figures below and the 9.9 µs / 0.3 µs reported before the owner review are
therefore not strictly comparable; these are the controlled ones.

| call | µs |
|---|---|
| `scoring_evidence_state` | 15.0 |
| `scoring_fingerprint_for_league` | 16.6 |
| `_contract_scoring_fingerprint` | 0.6 |
| `_scoring_identity_error` (whole gate) | 31.0 |

The freshness and season checks add ~7 µs over the pre-review fingerprint
lookup; the stamp/card comparison would have cost ~85 µs per call
unmemoized. Neither is on the same order as anything else in these
handlers.

## Scope note

This document covers W18-F001 only. W18-F002 (the cross-league sleeper
chimera) has its own RED at
`tests/api/test_cross_league_overlay_coherence.py`, whose module docstring
records why its fixture is deliberately independent of the real
`dynasty_main → dynasty_new` pair: that pair is only reachable today
*because* F001 lets two differently-scored leagues share a label, so a
regression built on it would evaporate at the moment F001 is repaired.

W18-F003 (realized-points correctness) is B7 and explicitly out of scope
(`docs/EXECUTION_PLAN.md:62`).

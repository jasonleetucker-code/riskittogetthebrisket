# Outlier integrity v2: architecture

**Status: design only.** Nothing described here is implemented, merged or switched on. The
DLF IDP hold (`dlf_offense_only_vote`) stays ON, the D4 hold (`dlf_values_rank_hill_vote`
OFF) stays in force, and every flag below ships default OFF. The acceptance criteria are in
[`OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`](OUTLIER_INTEGRITY_V2_PREREGISTRATION.md), which
was committed before any evaluation on the frozen populations.

Authority: owner directive 2026-10-20, "Fix the outlier filter and restore DLF IDP voting",
and its 10:20 UTC addendum (hold D4 for V2). The owner's earlier Option 3 decision (keep the
DLF IDP hold; activation only on explicit owner approval) still binds. Product authority
remains with `docs/EXECUTION_PLAN.md` and the owner records; this document governs only the
design of a default-OFF challenger.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 1. The problem in one paragraph

The incumbent per-row filter (`data_contract._hampel_filter_per_player`: K 2.75, MAD scale,
1,000-point floor, n ≥ 4) asks one question, "is this vote far from the row median?", and
uses the row's own votes to decide how far is far. On IDP rows three of four votes often sit
on one coordinate by construction (FantasyPros IDP, DLF IDP and DLF Rookie IDP are priced
through IDP Trade Calculator's own player order), so at n = 4 the MAD collapses and the band
becomes a fixed 1,000 points. Adding DLF switches the filter on for 158 IDP rows and drops 31
legitimate votes on 30 rows, moving seven players by 34-54% when DLF's own vote moves none of
them by more than 5.5% (reproduction: `outlier_integrity_v2/rootcause/`). D4 does the same on
12-14 offense rows at smaller size (Theo Johnson −7.4%). V1 (`outlier-corroborated-v1`, PR
#1847) fixed the legitimate-vote losses but failed its adversarial gate: per-row magnitude
alone cannot separate a ×0.2 corruption from a protected dissent of the same size, and it had
no identity, provenance or self-history evidence.

## 2. Design principle

**Magnitude alone never proves corruption.** A ×5 or ×0.2 corruption in the deep tail moves
a vote about ln 4.3 ≈ 1.46 in the implied-rank coordinate, comparable to legitimate dissent
(the most distant of the 31 protected votes, Jacob Rodriguez's FantasyPros vote, sits 1.17
from the nearest other provider, and protected dissent elsewhere on the board is larger). Rejection therefore
needs a second, independent kind of evidence: identity, feed provenance, structure, or a
discontinuity in the source's own history. Each kind lives in its own layer, and each layer
emits a specific, named reason.

The order is unchanged around the new layers:

```
freshness / health weighting  →  A identity  →  B source + normalization integrity
  →  C legitimate disagreement  →  existing B10 family cap  →  existing count-aware blend
  →  D confidence (existing owner, unchanged gate)
```

## 3. Flags and seams (one owner, no second engine)

| flag (all default OFF) | owns | change class |
|---|---|---|
| `outlier_integrity_v2` | master switch; dispatches the per-row decision | challenger slot (mutually exclusive with V1's `outlier_disagreement_policy`; startup asserts both are not on) |
| `identity_evidence_v2` | Layer A verdicts inside `src/identity/resolution.py::match_row_to_source_entry` | identity owner |
| `payload_provenance_guard` | B2: proven payload-path values become absent, the existing CSV fill supplies the vendor's preserved board | ingestion |
| `rookie_ladder_fail_closed` | B1: an untranslated rookie-ladder vote is withheld | normalization owner |
| `source_rank_history_record` | U4: record-only `source_rank` lane in `src/history` (no effect on values) | history owner |
| `integrity_holds_as_withheld` | D-1: held and unresolved votes become B11 lost-evidence seats | confidence |

* With every flag OFF the board is byte-identical (`scripts/golden_board.py` +
  `scripts/board_diff.py --expect-no-value-change`) and `CONTRACT_CSV_JOIN_V1` keeps its
  24,024 / 24,024 parity.
* **One dispatcher feeds every filter call site**: the challenger slot (~`data_contract.py`
  13116), the B11 lost-evidence replay (~13164, so voting and confidence seats agree), the
  second ranking pass (~15254), and PR #1817's `_two_way_alt_center`, which today calls the
  incumbent filter directly.
* V1's board screen (`rank_with_board_screen`) is **superseded, not run alongside** — V2
  takes V1's slot in the challenger chain, so there is never a second owner of "is this
  board mis-scaled".
* Reason codes are added to PR #1831's `src/sources/voting_status.py` in coordination with
  that PR, never forked.

## 4. Layer A — player identity

**Why:** V1 caught 15% of wrong-player cases because it looked only at numbers. A vote for
the wrong player is an identity fact, decidable from identity evidence, and should never
reach a statistical test. There is no second matcher and no fuzzy matching on the board path:
the layer lives inside the canonical join (`src/identity/resolution.py`).

**Upstream evidence it needs** (each its own named change):

* **U1** — `_parse_source_csv_cached` carries the source's own published position, team, age,
  vendor id, Sleeper id, rookie class and raw display name (today the tuple drops them);
  `CsvJoinDecision` gains a per-observation `IdentityVerdict`.
* **U2** — `Dynasty Scraper.py` stamps, per attached value on ktc / ktcSfTep / idpTradeCalc,
  the matching rung, the page position, the acquisition path (API intercept, autocomplete
  fallback, recovered partial) and (U2b) the observed SF / TEP toggle state.
* **U3** (scraper-ops) — name-only boards capture position and team where the vendor page
  shows them.

**Verdicts**, in order:

1. **CONTRADICTED** (refused): the Sleeper or vendor id resolves to a different player
   (generalises `refuse_sid_contradiction`); the raw name re-resolved through the owner gives
   a different player (catches surname captures such as the IDPTC "Jefferson" case);
   incompatible position group (allowing CANONICAL_V2 group drift, EDGE as DL or LB, and the
   `_TWO_WAY_PLAYERS` registry with #1817's alt-evidence rules); a rookie-board entry on a row
   outside that class; published age differing from Sleeper age by more than τ_age.
2. **UNRESOLVED** (refused, labelled *held*): two entries of one source collapsing on one key
   (Byron Murphy II / Jr.) without disambiguating id, position or team — replaces the loader's
   "keep the higher value" rule; same-group Sleeper homonyms the source cannot tell apart; a
   fuzzy or surname rung without agreement on position AND team or id; a team-only mismatch
   with no continuity in the source's own history (team lag with continuity is released).
3. **VERIFIED**: an id agrees, or name, position group and team all agree.
4. **NAME_ONLY**: the vote counts and is stamped `voting_name_only_identity`.

A refused observation is **absent** — never zero, never another player's value.

**Stated boundary:** Layer A cannot protect a name-only board. Twelve voting boards publish
only names today (dlfIdp, dlfRookieIdp, idpTradeCalc, dlfSf, dlfRookieSf, ktc, ktcSfTep,
fantasyCalc, OTC, DynastyDaddy, Flock, Navigator) and hold about 63% of material
wrong-player cases. U3 is what closes that gap, and it can only be shown on boards collected
after it ships.

## 5. Layer B — source and normalization integrity

**Why:** the historical failures that matter were whole-source or whole-segment faults, not
row faults: rookie boards voting untranslated within-class ranks (22 boards), and IDP Trade
Calculator's October partial-fallback boards serving 1QB-scale values over its own preserved
SF+TEP CSV (3 boards). Those are decidable from structure and provenance, without statistics.
Layer B extends the existing owners (`dataset_integrity`, `dataset_state`, `freshness`, the
translation stamps, `scale_integrity_lost`) rather than adding a parallel health system.

* **B0 — format.** Existing `dataset_integrity` FAILED states, schema errors, non-numeric
  values where a value is declared. Missing stays missing: DLF's blank value columns and
  Yahoo's zeros vote by rank and are never read as 0. For value-plus-rank CSVs the vendor's
  own rank-vs-value Spearman must be −1 (FantasyPros IDP exempt by design).
* **B1 — structural normalization.** A `ROOKIE_LADDER_PAIRS` vote whose method is not
  `rookie_ladder_translation_*` is withheld as `normalization_untranslated` (today the loop
  `continue`s silently and the rookie rank votes as an overall rank). U5 adds a
  `translationFallback` stamp at that point. An IDP shared-market vote with no bridge and a
  value-direct source with no registered conversion are withheld, as today. **Dependency
  propagation:** a vote translated through a quarantined backbone or ladder inherits
  `normalization_dependency_unavailable`, using the existing `scale_integrity_lost`
  declarations.
* **B2 — feed provenance.** For sources with both a payload copy and a same-run CSV copy
  (idpTradeCalc, ktc, ktcSfTep), per position group m_g = median ln(payload / CSV). A healthy
  board gives exactly 0.000. Board-level proof: |m_g| > ε in ≥ 2 groups with ≥ 15 rows and
  ≥ 80% sign agreement, or a U2b stamp of SF / TEP off on a fallback capture. Row-level proof:
  |ln(payload / CSV)| > ln 2. Coverage collapse and fallback share are supporting evidence
  only (the same fallback produced correct values on 2026-08-03 and 08-06). On proof the
  proven payload values are treated as absent and the existing CSV-fill rule supplies the
  vendor's own preserved board, aged by freshness. Requires an additive `sourceProvenance`
  stamp keeping the CSV value beside the payload value.
* **B3 — segment integrity**, in the vote coordinate u = ln(10 + 500·p), against the median of
  the source's previous 3 accepted boards (history lane):
  * **B3a conservation** per source × asset class: a correctly normalized board only
    redistributes rank, so its class-wide median residual against the leave-source-out
    reference cannot jump. A jump ≥ max(6·τ_board, ln 1.25) quarantines the source × class
    (`normalization_scale_error`). Position-zero-sum moves cannot fire it.
  * **B3b per position group** (QB / RB / WR / TE / DL / LB / DB, n ≥ n_min): direction error
    (Spearman vs the leave-source-out consensus ≤ ρ_min) and gross scale error
    (|median signed deviation − baseline| ≥ τ_gross) are hard. A non-gross shift is
    quarantined only with B0 / B1 / B2 proof on the same source build; otherwise the votes are
    kept, stamped `segment_break_unproven`, and an advisory is raised. **The per-position
    scope is the fix for the mechanism V1 missed**: pooled offense let opposite QB and WR/RB
    shifts cancel (−0.11 to −0.20 against a 0.405 limit).
  * Release only when the evidence returns within bounds, never on a timer. Picks are
    report-only (deferred by authority).
* **B4 — per-observation continuity**, against the median of the source's own last 3 accepted
  observations of the player (U4 history lane). A vote is **held** only if all hold: the jump
  exceeds τ_c(source, depth band); it moved AWAY from the leave-provider-out reference
  (|u_now − ref| − |u_prior − ref| ≥ ln 1.5 and |u_now − ref| ≥ ln 2) — so moves toward
  consensus are never held; no other provider lies within ln 1.25; no other provider co-moved
  in the same direction by at least half as much (news). With no prior observation B4
  abstains.

## 6. Layer C — legitimate disagreement

**Why:** once an observation passed A and B, disagreement is opinion. The incumbent's failure
was a scale estimated from the row it judges; Layer C uses no row-estimated scale at all.

One rule. Remove vote o only if ALL hold:

1. the row has ≥ 3 **providers** (`source_lineage.provider_of`: DLF's boards are one provider,
   KTC Crowd and KTC Trades are one provider);
2. a corroborated reference exists: ≥ 2 other providers within ln 2 of each other. A
   translated vote and its own backbone (FantasyPros / DLF / DLF Rookie IDP with IDP Trade
   Calculator; rookie boards with KTC Crowd) do not form that pair by themselves — this uses
   declared translation lineage, so it can only reduce rejections;
3. o's nearest distance to any vote of ANOTHER provider exceeds τ_C (≥ ln 4);
4. o is not persistence-confirmed (≥ 2 consecutive accepted observations within τ_c of u_o);
5. o's family holds less than half of the capped weight;
6. at least 2 providers survive.

Decisions are simultaneous and pairwise, so order does not matter. Numerical similarity never
merges anything. There is no MAD, no row-estimated scale and no 1,000-point floor. Kept votes
more than ln 2 from every other provider are stamped `kept_dissent` for information.

* **Monotonicity (restated precisely):** in a row that already meets guards 1, 2 and 5, adding
  any vote never turns a retain into a drop (adding a vote can only shrink nearest distances).
  Adding a vote can newly satisfy a guard, so the property is not claimed unconditionally.
* **Duplicate property:** a duplicate value under a new provider cannot narrow any band.
* The owner example (5000 / 5100 / 5000 / 3000) keeps Draft Sharks: its nearest distance is
  far below ln 4.

## 7. Layer D — confidence

**Why:** the directive forbids a second confidence engine. `src/api/confidence.py` and
`config/confidence/gate_v1.json` are unchanged. Kept dissent already lowers confidence
through the agreement axis. A / B / C exclusions behave like today's filter drops (the family
stays eligible, so coverage can only fall). The B11 lost-evidence replay uses V2, which also
removes the production defect where the incumbent statistic decides 28 IDP confidence seats.
**D-1** (`integrity_holds_as_withheld`, separately evaluated) makes held and unresolved votes
lost-evidence seats so a hold can never raise confidence.

Unchanged by every layer: Hill constants and curves, `_RANKING_SOURCES` weights, correlation
groups, family caps, freshness policy, Package VA, `geom_q078_v1`, Trade Calculator fairness
math and the Trade Finder.

## 8. Three tiers of treatment

| tier | what | treatment |
|---|---|---|
| proven invalid | A contradiction; B0 format; B1 untranslated + dependants; B2 provenance proof; B3a conservation break; B3b gross / direction error | excluded with a hard reason and explicit scope; lifts only when the evidence returns within bounds |
| suspicious, unproven | B4 discontinuity; A team-only or low-evidence ambiguity | **held**, not rejected. Released on the first of: the next content-distinct fetch reproduces the value within τ_c; another provider co-moves or comes within ln 1.25; a cap of 2 content-distinct fetches or 48 hours (then it votes and a source-health alert is raised). A hold never becomes a permanent exclusion without hard evidence. |
| legitimate dissent | everything else | votes at its established weight; only the narrow Layer C cold-start tail rule can drop it |

The cost of holds, stated plainly: the first vendor to react to real news is delayed by one
fetch unless another provider has already moved.

## 9. Transparency

Each vote gets `sourceRankMeta[k].integrity = {status, primaryReason, otherReasons, scope,
evidence, versions}`. Primary reason precedence: identity > format / feed > normalization >
freshness > held > tail. No reason is emitted unless its layer actually tested for it.

| directive §10 category | codes |
|---|---|
| voting normally | `voting`, `voting_name_only_identity` (informational) |
| valid but disagreeing | `kept_dissent`, `segment_break_unproven` — never displayed as invalid |
| invalid player identity | `identity_contradicted:<sleeper_id\|vendor_id\|join_inconsistent\|position_group\|rookie_class\|age>` |
| source-format error | `source_format_error:<schema\|non_numeric_value\|vendor_rank_value_inconsistent\|format_toggle_off(sf\|tep)>` |
| normalization / scale error | `normalization_untranslated`, `normalization_dependency_unavailable`, `normalization_scale_error@src/class[/pos]`, `normalization_direction_error@src/class/pos`, existing `withheld_no_bridge` |
| stale source | existing `freshness_or_health_zero_weight` |
| broken feed | `broken_feed:payload_provenance_conflict`, existing `dataset_integrity` FAILED |
| missing observation | absent and counted as missing evidence, never 0 |
| temporarily held by policy | `dlf_offense_only_vote`; the D4 hold; `held_pending_confirmation:observation_discontinuity`; `identity_unresolved:<ambiguous_in_source\|homonym\|low_evidence_rung\|team_only_mismatch>` — shown as "held pending confirmation", never "corrupt" |
| rejected by a justified integrity rule | `extreme_uncorroborated_tail` — shown as "extreme and uncorroborated by any other provider; no history yet", never as corruption |

Source-health alerts that are not exclusions: `persistent_gross_dissent` (more than τ_C from
every provider for ≥ 3 boards; for human review, the vote stays) and segment advisories.

## 10. Why this design and not the alternatives

Three candidates were designed and judged against the directive (scorecard in the
preregistration §2):

* **Structure-first (this design, 62 / 80).** Layer C uses no row-estimated scale, which
  removes the measured root cause structurally rather than by tuning.
* **Corroboration-first (53 / 80).** Safest for opinion but weakest against corruption: its
  Layer C cannot reject without self-history, and a persistent corruption becomes an
  "established view". Its provenance test, dependency propagation, provider-level
  corroboration units and identity rules are grafted in.
* **Reliability-prior (56 / 80).** Most honest evidence, but a fitted ~200-cell per-family
  error model is a new model next to source-reliability weighting, which §8 forbids changing;
  its no-history configuration also kept or dropped Rodriguez's FantasyPros vote depending on
  whether DLF was present — the exact defect class. Its rank-mass conservation check (B3a) and
  "jump away from the reference" condition (B4) are grafted in.

Rejected outright, per the directive: raising the Hampel threshold, disabling filtering,
down-weighting or winsorising dissent, equal-weighting.

## 11. Known residual risks (named, not papered over)

* Wrong-player detection on name-only boards needs U3 and can only be demonstrated
  prospectively; until then the wrong-player gate is expected to fail.
* AD1b (×0.2) reaches 90% only when the corruption arrives against clean history; a persistent
  ×0.2 corruption tops out near 82% if every protected vote is kept.
* The `source_rank` history lane is new production state; with it missing V2 must fail closed
  to A + B0/B1/B2 + C and say so.
* The persistence exemption and capped holds protect long-lived corruption that reproduces
  every fetch; only A, B or human review of `persistent_gross_dissent` catch it. Correlated
  multi-source anomalies remain undetectable (the pipeline's existing named limitation).
* B2 changes which observation votes (payload → preserved CSV); whether production served the
  H2 values at the time cannot be shown locally.

## 12. Rollback

Every flag OFF and restart. Flags are read once per process; there is no runtime toggle. The
OFF state is byte-identical to the incumbent board.

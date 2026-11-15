# Signals IDP round 2: preregistration (Candidate F, gates, controls)

**Registration only.** No Candidate F vote, statistic or verdict has been computed on any
Signals release. Nothing here changes a served value, a vote hold, a flag default, a
threshold or a source weight. If a definition below changes after results are seen, the
change is reported as a deviation beside the original; the rule here is never silently
replaced.

* **Authority:** owner directive 2026-10-19, "Get Signals Fantasy IDP Fully Voting". Its
  verbatim record is `docs/owner/SIGNALS_IDP_VOTING_2026-10-19.md` (release train 13); it
  is referenced here, not copied.
* **Machine-readable twin:** `gates.json` in this directory. The on-box verifier
  (`scripts/verify_signals_onbox.py`) embeds it, and a test pins the embedded copy to this
  file, so the verdicts are computed from exactly these thresholds.
* **Frozen files:** `FROZEN_SHA256SUMS` lists the sha256 of this file and `gates.json`, one
  line per file. Results are appended in a separate `RESULTS.md`, so appending them never
  changes a frozen hash. (The model-lab record hashes the whole Signals integration doc,
  which changes every time a result is appended there.)
* **Round 1 stays as recorded.** Candidate A FAILED round 1 (criteria 6 and 6b,
  `docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §10.8.1). It is never redefined; it is the
  comparison baseline and negative control NC1.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. Disclosure

> Candidate F's design was informed by Signals-derived October 17 **aggregates** (coverage
> counts and failure statistics) and by public-data replays. No parameter is learned. R1 is
> the next release of a highly autocorrelated vendor board, so it is fresh only in a weak
> sense.

The replays that informed this design used no Signals data. They built a synthetic voter
with the bridge's own within-family order (N0) on the public board. What they establish
and what they do not is in §2.

## 1. What is being decided

For each defensive family F in {DL, LB, DB} separately: may Signals' within-family IDP
order vote in the canonical dynasty board, through the coverage-aligned crosswalk F, under
the October 17 thresholds applied in the **served** configuration?

The answer is one of: **activate** (every gate passes on R1 and R2, or every failing
component carries an accepted disposition, §6), **stay in shadow with the reason
recorded**, or **BLOCKED** with the exact missing evidence.

## 2. What round 1 showed, and what it did not

Three mechanisms dominate the October 17 statistics. None of them depends on Signals'
order:

1. **DL tail movement.** The approved 0.30 single-source haircut is lifted on off-cap DL
   rows when a second family votes. A row resting on one anchor A moves from 0.3·A to about
   A + 0.1(S − A), roughly +227% to +247% across plausible agreement.
2. **LB and DB signed bias.** A vote at the bridge's family level inherits the bridge's
   (IDP Trade Calculator's) placement of LBs and DBs relative to the other families, which
   the rest of the voting panel disputes. Committed evidence
   (`docs/sources/evidence/IDP_REHAB_2026-10-18/idp_rehab_eval.json`): IDP Trade Calculator
   against the leave-one-out mean of the other voters is LB −0.118, DB −0.223, DL +0.050.
   The round-1 instrument also counted observations that were not voting and accepted a
   single "other" source.
3. **The one offense row.** The two-way boost's alt ladder maps `overall_idp` source ranks
   onto the `rankDerivedValue` of all IDP rows, so a DL-only change can move the two-way
   player's DB-family alt value. That is a defect on `main`; PR #1817 owns the fix.

DB also carries a real coverage-displacement defect in Candidate A: 24 bridge-priced DBs
were withheld because Signals-only rows shifted every later Signals rank.

**The N0 replays do not show that a voter with no opinion fails the gates.** They show that
the bridge entered a second time fails them: N0 takes the bridge's within-family order and
family ladder and prices them on a GLOBAL Hill curve fitted to the bridge
(`src/canonical/player_valuation.py`). Signed medians are nearly blind to ordering (in a toy
simulation a random within-family permutation reproduced the round-1 6b statistic 95% of the
time, a reversed order 84%), so the close match between N0 and Signals is uninformative
about Signals in either direction.

## 3. Candidate F: `signals-idp-F-coverage-aligned-v1`

The only candidate that can be promoted this round.

### 3.1 Frozen common definitions (per family F)

| Symbol | Definition |
|---|---|
| β | The single contributor of `build_bridge_ladder` (IDP Trade Calculator today). More than one contributor withholds every Signals vote (`family_positions_undefined_multi_bridge`) and fires an alert, because turning `multi_bridge_ladder` on would otherwise halt Signals IDP silently. |
| R_F | Board rows at position F with `canonicalSiteValues[β] > 0` |
| c(p) | p's slot in `family_ladder(F)`, ordered by (−v_β, lower(one pinned name key)). σ and c(p) use the same key. |
| S_F | Signals' phase-1 eligible set: a native value on the family board, the row held at position F |
| σ | Signals' order: **competition** ranks of the native value within the family (the code comment says "dense"; the code computes competition ranks) |
| M_F | S_F ∩ R_F, with m = \|M_F\|; k_M(p) is p's competition rank within M_F |
| L^M | Ascending list of c(q) for q ∈ M_F |
| Hill_G(r) | GLOBAL `shared_market` pricing through the voting path's own pricing helper; fractional ranks are passed directly, never through `translate_position_rank` |
| Rookie rule | Signals IDP rookie rows are withheld this round (`rookie_unobservable_by_basis`): Signals' IDP order comes from a per-snap model that cannot observe a rookie with no snaps, and the rule keeps Signals out of the current-year slot-pick tether |
| Withheld reasons (never zero) | `unmatched_in_reference`; `family_positions_undefined_multi_bridge`; `reference_withheld`; `sleeper_id_contradiction`; `not_a_within_family_rank`; family mismatch; `rookie_unobservable_by_basis` |

### 3.2 The vote

For p ∈ M_F in a tie group of size t starting at competition rank k:
r_F(p) = mean(L^M[k−1 … k+t−2]), and the vote is Hill_G(r_F(p)). Signals-only rows are
withheld.

**Structural properties, each tested:**

* with no ties the votes are a permutation of the bridge coordinates (ties make this
  approximate, because Hill(mean rank) ≠ mean(Hill));
* no vote falls outside [min L^M, max L^M];
* injection invariance: adding Signals-only rows changes no matched vote;
* no bridge-priced matched player is withheld;
* votes are monotone in σ.

**What F gives up, stated plainly:**

* Signals' unique coverage (about 16 DL and 25 DB rows in round 1 were Signals-only);
* Signals' within-family spacing (F uses the bridge's slot spacing);
* any cross-family level of its own: **F's level is the bridge's**.

F contributes **Signals' within-family order only**. Every published vote carries
`levelSource: "idpTradeCalc"` and `contributes: "within_family_order"`, so no consumer reads
it as a cross-family price Signals asserted. Rows withheld by the translation are stamped
`withheldByTranslation`, so the confidence gate does not score them as rows Signals failed
to cover.

### 3.3 Diagnostics (none promotable this round)

| Id | What it is | Why diagnostic only |
|---|---|---|
| H | Geometric moving-window ranks (window 0.05·m) | It creates disagreement at real bridge tier gaps; the window constant was chosen after seeing the DL 7→8 cliff |
| G | F plus Signals-only rows interpolated between matched neighbours | Assigns bridge-level coordinates to players the bridge never priced; the only route that recovers unique coverage, so it is reported |
| N0 | The bridge's own order, priced as A | Negative control NC4, not a floor to subtract |
| A | The failed Candidate A | Baseline and negative control NC1 |
| K | Panel-median level | Circular |
| I | Isotonic (PAVA) fit | Fitted in-sample |
| J | Draft Sharks IDP as reference | The information diagnostic, §8 |
| B | Proportional percentile | Existing diagnostic |
| F × deep tail | F priced with `idp_deep_tail_native_challenger` on | The region past rank 500 was flagged by owner decision 6 of 2026-10-18 |

**Directive Candidate 4 (completed-trade calibration) is UNSUPPORTED for 2026.** Round 1
had 0 scorable trades; the own-league format bracket began around 2026-10-02; concentration
and Kish tooling do not exist. Re-entry needs a census of at least 30 IDP
NATIVE_COMPARABLE / VALIDATED_TRANSFORMABLE underlying trades per family in
`data/market_trades/underlying_trades.sqlite` (the Sharp cohort included), concentration
and Kish tooling, and a validated IDP-scoring translator or multi-season accumulation.

### 3.4 Candidate N (native league value): slot reserved

A native league-specific Signals value may be admitted to evaluation only under the
admission rules in `gates.json` (`candidates.N.admissionRules`), written before any
authenticated probe runs. If admitted, its cross-family order would be Signals' own, so it
additionally needs rank-space consistency against references (leave-one-reference-out) and
the §8 information diagnostic; trades are recorded as INSUFFICIENT. A roster-dependent value
is leagueKey-scoped and cannot be a canonical vote (CLAUDE.md core split), so it is
rejected. Its absence never blocks F.

## 4. Data each candidate is fit on and evaluated on

| | Fit on | Evaluated on |
|---|---|---|
| F | Nothing learned. Design informed by round-1 aggregates (disclosed, §0). | **R1** and **R2** (below). Activation requires agreement on both. |
| Diagnostics | various | R1 and R2, reported only |

* **R1:** the first Signals IDP release whose `asOf` is after the merge of this
  preregistration to `main`, whose `contentSha256` differs from `6ec7bff6bd11`, and on
  which at least 10% of matched rows change within-family rank against `6ec7bff6bd11`. If
  the change is smaller, wait for the next release.
* **R2:** the next release meeting the same rule against R1.
* **Deadline:** if no qualifying R1 exists by **2026-11-16**, the unit reports
  `BLOCKED: no_qualifying_release` with the evidence. It does not wait silently.
* **Champion:** the board served at evaluation time. Flags are read from the local
  `GET /api/status` `featureFlags`, never from `.env`.

**D1 quarantine.** The diagnostic run D1 (`--mode diagnose`) computes Candidate A, N0, and
the haircut, Hampel, coverage and Hill/pick decompositions **only**. It computes no F, H or
G vote or statistic on any release before R1. Its frozen tree is pinned to IDP release
`6ec7bff6bd11`, rendered from the release JSON, and it refuses to run without that release.
The verifier enforces this in code: a D1 build that switches on the F flags raises. Round-1
code has no per-family flag, so D1 isolates a family by giving the other two families empty
boards (present, no rows, no vote).

**Gate mode before the implementation unit.** E1 and E2 build F through the per-family flags
and `signals_idp_xwalk_v2`. Until the deployed code registers them, every F build is refused
(`unregistered_flag`) and every family verdict is VOID. That is the intended fail-closed
state, not a result.

## 5. Gates: the October 17 thresholds, binding in the served configuration

Each family is computed in an **isolated build** (family F promoted, the others as served);
the combined three-family build is reported as well. The report keeps engineering
correctness and empirical valuation quality in separate sections.

### 5.1 Engineering correctness

| Id | Criterion | Threshold |
|---|---|---|
| G1 | No Signals-created cross-family order | 0 |
| G2 | Every vote in `shared_market` coordinates | all |
| G8 | Tests: missing ladder, bad identity, unsupported family, stale source | pass (CI) |
| Integrity | Duplicate Signals observations on a row; `sleeper_id_contradiction` among voting rows; family-mismatched rows voting; stale or invalid observations voting; shadow `wouldContribute` ≠ promoted `valueContribution`; extrapolated votes; rookie votes | each 0 |
| G6b-structural | \|b_F − b_N0\| ≤ 5% on the corrected panel. Under F it verifies coverage and permutation integrity on real data; **it is not evidence of valuation quality** | reported |

### 5.2 Empirical (thresholds unchanged from round 1)

| Id | Criterion | Threshold |
|---|---|---|
| G3 | Watch-list entries within the row range +15% (computed privately; publicly only `{entries, withinRange}` when entries ≥ 5) | all |
| G4 | Signals' own Hampel drops | ≤ 5% |
| G4-X (new) | Hampel drops **caused** by Signals in other sources: 0 drops of the independent-level anchor (Draft Sharks IDP) in the elite (IDP rank ≤ 100) and starter (101–250) bands; total caused drops ≤ 5% of the family's voting observations; every drop explained by its filter stamp | as stated |
| G5 | Family share of the overall top 200 | moves ≤ 3 pp |
| G6 | IDP relative movement median ≤ 2% and p90 ≤ 8%, served configuration, newly priced rows counted (as a 100% move, and counted separately); **0 offense player rows** (a hard FAIL until #1817's two-way fix is deployed); tethered picks reported separately | as stated |
| G6b | Per-family signed median vs other sources on the **corrected panel** (§6), at least 2 other voting sources | within ±5% |
| G6-shift (new) | Board-level per-family mean shift; absolute and relative movement by mechanism class | reported |
| Confidence | Transition matrix and per-axis deltas. **Unjustified inflation** counts bucket rises driven by haircut-flip agreement, Signals being the deciding fifth independence head, Signals supplying the agreement share that crosses 0.75, or Signals' agreement credit under a borrowed level | reported per family; whether a borrowed-level vote earns agreement credit is owner decision 1 |
| G7 | Independent fresh-context review, which must classify Signals' IDP horizon (dynasty vs seasonal) | required |
| G9 | Completed trades | INSUFFICIENT below 30; non-blocking; **never presented as validation** |

## 6. Failing components: repair, measurement correction, or owner acceptance

The earlier revised gates G6′ (haircut and Hampel switched off) and G6b′ (difference against
N0) are **withdrawn as promotion gates**: G6b′ is satisfied by construction under F and would
also have passed the failed Candidate A; G6′ measures a configuration production does not
serve. A family that fails G6 or G6b is decomposed, and each failing component carries
exactly one disposition: `REPAIRED`, `MEASUREMENT_CORRECTION` or `OWNER_ACCEPTED`.

| Component | Disposition available |
|---|---|
| Panel defects (non-voting observations; a single other source) | **Measurement correction**, documented prospectively: count only observations with `appliedWeight > 0` that are not `hampelDropped` and not `contributedToBlend: False`; require at least 2 other sources. The round-1 script-panel number is always printed beside it. This changes the instrument, not a threshold, but it does change the panel, so `ODR-SIGNALS-IDP` needs explicit owner acknowledgement (owner decision 4). |
| Borrowed-level bias (the LB/DB floor) | Cannot be repaired within F. **Owner decision 1:** (a) signed-bias gates do not apply to a source without a level opinion, and the consequences are gated instead (G4-X, G6-shift, confidence); or (b) G6b stays binding and LB/DB stay in shadow until a non-bridge level source exists. |
| Hill misfit and the pick-inflated coordinate | Shared with FantasyPros IDP and DLF IDP. Reported; the repair belongs to the Hill and bridge owners. Under 1(a) it is not a Signals-specific blocker. |
| DL haircut flips | **Owner decision 2:** wait for #1817's haircut finding, or accept the flips explicitly. No new served haircut bound is invented here (one concept, one owner). |
| Hampel knock-on drops | Gated by G4-X; the filter belongs to the outlier lane. |

### 6.1 Mandatory negative controls

Any revised or decomposed statistic used for a disposition must be failed by each control,
or the statistic is VOID for the round:

* **NC1:** Candidate A at DB. In D1 it is the A build; in the gate (where A can no longer
  vote) it is A's published shadow vote against the served panel.
* **NC2:** a seeded random within-family permutation of Signals' matched order (seed
  20261019), median over 200 draws, the panel held fixed. The verifier reassigns the
  isolated build's own sorted votes, so no second pricing is involved.
* **NC3:** a fully reversed within-family order, the panel held fixed.
* **NC4:** N0 itself (a build: priced as A in D1, as F in the gate).

Scope: NC2, NC3 and NC4 are evaluated per family and void the statistic for that family;
NC1 is evaluated at DB and, if it passes, voids the statistic in every family. A control
"passes" when its value meets the threshold the statistic is used against (for the
corrected-panel G6b, |median| ≤ 5% on at least 20 rows).

### 6.2 Falsifiable premises

If D1 falsifies one of these, every disposition that depends on it is void:

* **P1:** haircut flips account for at least 80% of DL rows at or above the DL movement p90
  on the box board.
* **P2:** the box-board N0 LB and DB floor on the corrected panel lies within [−6%, 0%].
* **P3:** IDP Show is zero-weight on the evaluation board (otherwise the panel composition is
  re-recorded).

### 6.3 Reproduction verdicts for round 1 (D1)

D1 states, for each of the directive's eight round-1 figures (343 of 396 rows moving; median
1.37%; p90 30.07%; 2.9% Signals outlier drops; LB −6.24%; DB −9.95%; 1 offense row; 0
trades), whether it was `REPRODUCED` within tolerance, `NOT_REPRODUCED`, or `EXPLAINED`,
with absolute and relative movement given separately. Tolerances: counts exact; percentages
within ±1.0 point; tail statistics within 10% relative. The round-1 inputs are approximately
recoverable (the 10-17 payload and public CSVs are tracked at `f9d1994e59`, Signals releases
are never pruned), but exact reproduction is impossible: round 1 recorded no input pins, and
the deployed code has drifted by default-off challengers since.

## 7. Why each piece exists (short)

* **Isolated per-family builds:** directive Phase 7 asks for independent activation, so each
  family is judged on its own blast radius.
* **R1 and R2:** weekly releases overlap heavily; the 10% rank-change rule and the
  two-release requirement mitigate autocorrelation without making the data independent.
* **G4-X:** with Signals as a fourth IDP voter the Hampel filter switches on (minimum n = 4),
  and an extra vote at the bridge's level pulls the median and MAD toward the bridge, which
  can drop exactly the voters whose level owes least to it.
* **Confidence inflation:** under F the vote sits at the bridge's level and anchored IDP
  values are about 90% anchor, so agreement credit is near-automatic.

## 8. Independent-information diagnostic (directive Phase 5)

* **Target:** Draft Sharks IDP (native cross-market, not ladder-translated).
* **Builds:** leave-Draft-Sharks-out, without the Signals family, with it, and with N0 in its
  place.
* **Metrics, within Draft Sharks coverage, per family:** rank-space Spearman correlation and
  median absolute log error against Draft Sharks; on pairs where Signals' and the bridge's
  orders disagree, the share on which Draft Sharks sides with Signals.
* **Verdict rule** (constants in `gates.json` `information`): POSITIVE when the with-Signals
  Spearman beats both the without-Signals and the N0 build by at least 0.01 **and** Draft
  Sharks sides with Signals on at least 55% of at least 50 discordant pairs; NEGATIVE when
  both Spearman deltas are at most −0.01 and the side-with share is at most 45%;
  INSUFFICIENT below 20 matched rows per family or 50 discordant pairs; otherwise NEUTRAL.
  The constants are priors chosen before any result. Discordant pairs share players, so the
  share is not a test statistic with independent trials.
* **It is an information metric, never an agreement penalty.** Draft Sharks coverage is
  shallow (about 55–68 rows per family) and its scale proof is disputed between
  `source_lineage.json` and `bridges_v1.json`, so INSUFFICIENT is likely below starter depth.
  Activating a family whose verdict is not POSITIVE is owner decision 3. Absence of
  contradiction is not validation.
* Verdict wording: `ENGINEERING PASS|FAIL / INFORMATION: POSITIVE|NEUTRAL|NEGATIVE|INSUFFICIENT`.

### 8.1 Horizon check (dynasty value or season projection?)

The lineage record calls Signals' IDP order a per-snap projection model with no market input.
If the order is mainly current-season production, voting it in the dynasty board breaks the
source-domain boundary whatever the translation. The verifier reports, per family on M_F:

* the within-family Spearman correlation between Signals' order and the bridge's order;
* the **age gradient of the ordering residual**: Spearman(age, (k_M(p) − bridge rank within
  M_F) / m). A dynasty value prices young players above equal-production veterans, so a
  projection-like order shows a residual that rises with age (Signals ranks older players
  higher than the market does).

The share of disagreement explained by prior-season points per snap needs vendor features
the board does not carry; it is reported privately when available and never published. The
horizon is classified by the independent review (G7), not by a threshold here: the
diagnostic may be ambiguous, and an ambiguous horizon is not a pass.

## 9. Native-value investigation (directive Phase 3)

### 9.1 Tier 0: public web-app bundle, off-box, unauthenticated (run 2026-10-19)

Method: two unauthenticated GETs from a sandbox with no credentials (the app's HTML entry
page and its single entry module, about 6.4 MB; two lazily imported spreadsheet libraries were
not fetched). Bundle content sha256 prefix `f13ceb30d089`. Read with plain-text pattern
searches only. The public projection below carries booleans and counts; operation names,
field names and hosts beyond those already recorded in the repository are not published.

| Finding | Value |
|---|---|
| Named GraphQL documents embedded in the bundle | 5 (3 queries, 2 mutations); none reads a league-specific player value |
| Data-model introspection shipped with the app | 78 models, 90 secondary-index list queries |
| Custom (resolver-backed) queries, mutations or subscriptions in that introspection | 0 |
| The IDP dynasty value model (the one the collector reads) declares a scoring, roster, lineup or league input field | **false** |
| Any model in the schema is a league-specific player-value store | **false** (the four league-scoped models carry settings, history, accounts or discovery metadata, not player values) |
| The daily per-player value snapshot model also declares an IDP dynasty value field and an IDP positional-rank field | **true** (not collected today; same provider, so not an independent observation) |
| A separate REST API (an execute-api endpoint) is configured in the app | **true**; its routes were **not enumerated in this pass** |
| Host literals: FantasyCalc / KTC / Sleeper / other | false / false / true / true |

**Reading.** In the data schema the shipped app reads, there is no server-side league-specific
IDP value observation, and the IDP value model takes no league input. That matches the prior
(`src/sources/signals.py`: IDP `exactLeagueSettings` "not exposed"; league-exact offense values
computed in the browser over a FantasyCalc fetch, recorded 2026-10-03 and not re-verified
here). The REST API is the one place a server-side league value could still live. Answering
that, and questions 5 (scarcity or replacement applied?) and 6 (server or browser?), is the job
of Tier 0 in the probe (`scripts/probe_signals_native.py`, PR-P) and of the authenticated
tiers 1b, 1c and 2, which run only from merged and deployed code inside a verified-fresh token
window. **Current disposition of N: slot reserved, not admitted, prior low.** The native route
never blocks F.

### 9.2 Tier 1a: offline, on the box (pending)

Tier 1a reads the private release JSONs on the box with no network (verifier
`--mode native-offline`): counts per raw position; S1 (family tops within 5%; normalised
curves within ±5% at k = 12 and 24); the share of adjacent pairs on which value is monotone
in the vendor composite; a timestamp census; release-interval statistics. It runs in the
first `main` run after the verifier hardening merges. Its public projection is appended to
`RESULTS.md`. This preregistration does not depend on its outcome: S1 was already measured on
2026-10-03 (family tops within 4%), which is why F uses within-family order only.

## 10. Privacy (binding on every artifact of this round)

* No player-specific Signals value, no per-row Signals/anchor ratio, no credential, cookie,
  token or session timestamp in the repository, a PR, a workflow log or an artifact.
* Public projections carry counts, rates and quantiles only: no `max` or `min` anywhere;
  quantiles only when n ≥ 20, rounded to 2 significant figures; band cells below 20
  suppressed; an explicit allowlist of key paths (`gates.json` `privacy.publicAllow`).
* The watch list stays private; publicly only `{entries, withinRange}` when entries ≥ 5.
* A name blocklist (every board display name plus every name in the private release JSONs,
  case-insensitive and word-bounded) is checked against everything printed.
* Standard error goes to a 0600 file on the box; an uncaught exception prints only its class.
* Gate evidence is parsed from the artifact, never the log (Actions masking corrupts digits).
* Tests use synthetic values only.

## 11. Corrections to the round-1 record

These correct statements in `docs/sources/SIGNALS_FANTASY_INTEGRATION.md`; the doc keeps its
original text and points here.

1. **§10.2 "it adds none" is false.** Under the family crosswalk, Signals inherits the
   bridge's cross-family placement. FantasyPros IDP and DLF IDP translate their *own*
   overall-IDP ranks, so their DL/LB/DB interleaving is their own; Signals' is not.
2. **§10.8.1 "the −6.24% is genuine disagreement" is unsupported.** The borrowed level and the
   panel defects explain the floor without any Signals-specific disagreement; whether genuine
   disagreement remains is unknown.
3. **§10.8.1's DL haircut rebuttal used the wrong population.** It counted ranked DLs; the
   lifted haircuts sit on off-cap rows.
4. **The round-1 "one real collection first" was a minimum-interval skip.** The unit started
   by `--collect` exited successfully without collecting; the IDP evidence came from the timer
   run.
5. **The lineage record contradicts itself.** `source_lineage.json` calls Signals' IDP basis a
   per-snap `model_projection` with no market input, and also lists all six Signals keys under
   `signals-suspected-market-ancestry`. The contradiction is handed to #1817's lineage audit;
   similarity is not lineage.

## 12. Engineering-priorities applicability (AI_INSTRUCTIONS)

| Mechanism | Disposition |
|---|---|
| Source replay / provenance: a pinned frozen input tree with sha256 pins and a flag snapshot | APPLY_NOW (verifier) |
| Property tests for the crosswalk invariants | APPLY_NOW (implementation unit) |
| Architecture / import guard: one pricing helper; AST pin on literal flag reads | APPLY_NOW (implementation unit) |
| Typed API contracts for new stamps | ALREADY_COVERED by contract validation |
| Observability: per-release on-box monitoring | APPLY_NOW (alert, not gate) |
| Supply chain | NOT_RELEVANT |
| Database migrations | NOT_RELEVANT |

## 13. Owner decisions

Starting the work needs nothing beyond the directive. Activation needs the decisions listed in
`OWNER_DECISIONS_PROPOSED.md` (this directory), which also carries the proposed
`ODR-SIGNALS-IDP` text. Without an answer, the affected family stays in shadow with that
reason recorded.

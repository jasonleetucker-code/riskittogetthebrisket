# Public fairness consistency audit — Brisket Trade Advisor (2026-10-20)

**Status:** audit and recommendations only. No code on any audited branch was changed; no fairness
threshold was modified or activated.
**Historical body:** sections 1 to 12 describe the audited SHAs (`fae7209b6b` / `aa88b5c`, before train 17). Where they
say the advisor is "branch only", `fairness_bands_v2` is "not merged", `approvedFairnessVersion` is `null`, or a
follow-up is future work, read §0a first: it records the state on `main` and supersedes them. Line numbers in §2 and
§3 are the audited heads' and have moved on `main`.
**Authority:** owner decision record `docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md` §5 ("PUBLIC
CALCULATOR CONSISTENCY — IMPORTANT").
**Agent-OS-Receipt:** cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Summary

| question | answer |
|---|---|
| Does the public 2-team path use Team Context today? | **No — not at the current advisor head.** It did until `2bbe5d4bd` (branch only, never on `main`). |
| Does it subtract forced-drop release cost (`trade_decision._objective_value`) today? | **No.** The public answer reads the gross market band; roster capacity is not even computed on the public path. |
| Do the public 2-, 3- and 4-team paths use one calculation? | **Yes.** All three go through one function: `public_advisor.evaluate` → `analyze_service.analyze_trade_n(mode="market_fairness")` → `team_verdicts.team_fairness`. |
| Is any proprietary number exposed in the public payload or UI? | **No direct exposure found.** Residual: a binary fair / not-fair oracle permits slow reconstruction (already an accepted residual in the spec). |
| Verdict | **CONSISTENT with the owner's intent at `fae7209b6b`** (historical; re-verified on `main` in §0a). Five bounded follow-ups (§6); three of them only apply once `fairness_bands_v2` (#1886) lands. |

The research memo's description of the advisor is stale for the current head
(`docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` §10). It says the advisor "evaluates 2-team trades … with
**Team Context on**" and "maps 3–4-team trades through `public_category_from_net_band`". That was true **before**
`2bbe5d4bd`. The concern it raised — the public 2-team path inheriting the forced-drop over-charge (§5 of that memo)
— was real for that design and **does not apply to the current head**.

### 0a. Re-verified on `main` after train 17 (2026-10-21)

Train 17 merged the advisor lane (#1861) and `fairness_bands_v2` (#1886) into `main`. The harness was re-run on
`main@7f35463ef`, merged into this branch, with `--code-root .`, the same seed and caps 3, 6 and 8:

- **P1–P6 hold at every cap.** Bands read `fairness_bands_v2`.
- **The per-trade public digest is identical** to this audit's v2-overlay run (`8501804266dd…`), and the counts are
  identical too. The scratch overlay predicted the merged tree exactly.
- **The forced-release sentinel leaves every public result unchanged.**
- Evidence: `harness_cap{3,6,8}_main_7f35463ef.json`. `--compare-digests` against the overlay run returns identical.

**§6 follow-ups, as landed on `main`:**

| item | status |
|---|---|
| 1, FAIR from the band owner | done: `counts_as_fair_trade` |
| 2, private base | done: `largerPackageUtility` is read from the market lens |
| 3, contract fixtures | done: regenerated on v2 |
| 4, frontend | merged in the same train |

`approvedFairnessVersion` now names `fairness_bands_v2`. It was set by integration commit `bb9ae05c4`, citing the
owner's v2 approval (`docs/owner/FAIRNESS_V2_DECISIONS_2026-10-20.md`); the owner has not separately confirmed it as
launch approval (OD-3, the response floor and the flag remain). The launch gate still keeps the
advisor dark on its other conditions: the measured response floor, the source-permission record and the
`brisket_trade_advisor` flag. Nothing here activates it.

**Verdict unchanged:** CONSISTENT with the owner's intent.

## 1. Audited SHAs

| ref | SHA | role |
|---|---|---|
| `origin/claude/advisor-public-backend` (PR #1861) | `fae7209b6b819e1111d2155a497e20b068e7bea4` | public backend + the shared N-team engine (Lane C, with Lane A merged) |
| `origin/claude/advisor-hub-frontend` | `105f0748b92a0a52832ddcee516e0161a57a109d` | League Hub advisor UI; it merged the backend at `82ca5fa984` |
| `origin/claude/fairness-bands-v2` (PR #1886) | `19ec3f7394f019baa7d1b3ee0233ebea2877a3fd` | `fairness_bands_v2` (owner-approved prior, not merged) |
| `origin/main` | `aa88b5cc1b9cdee1568c750069a0cb1d3bbe231e` | no advisor code at all (`src/trade/public_advisor.py` absent) |
| audit base (this branch) | `e1eff9f5fc5aec746923334a2c5c7e2e5d8cb8ee` | — |

Both advisor heads moved during the audit; the first pass read `c5dfa95ed4` (backend) and `eb4ee475e4` (frontend).
- **Backend** `c5dfa95..fae7209`: a merge of `main`, plus `fae7209b6`. That commit makes the public side publish
  UNABLE instead of 503 when its F2 check withholds an engine FAIR / NOT_FAIR team, and it recomputes the overall
  from the public per-team states. Every result below was re-run at `fae7209`.
- **Frontend** `eb4ee47..105f074`: renders the `busy` / `timeout` admission refusals.

Historical comparison points:
- `2488f7557` is the last backend commit with the Team-Context public path.
- `2bbe5d4bd` is "feat(advisor): fairness-only, multi-team public contract over the shared N-team engine".
- `5e5f8f453` (the first advisor commit) is **not** an ancestor of `origin/main`, so the Team-Context public path
  was never served.

Citations are `path:line@sha`, where `fae7209` is the backend head and `105f074` the frontend head.

## 2. How the current head computes the public answer

1. **Route** `POST /api/public/league/trade-advisor/analyze` (`src/api/public_trade_advisor_api.py:879-951@fae7209`).
   It checks the rate limit, body cap and schema, then runs `public_advisor.snapshot`, then
   `public_advisor.validate` (the ledger owner, public policy `send_and_receive`), then `_evaluate` (admission
   control + single-flight), then `_analyze_body`.
2. **Evaluation** — `public_advisor.evaluate` (`src/trade/public_advisor.py:698-745@fae7209`). It makes ONE engine
   call (`:716-718`): `analyze_service.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)`.
3. **Engine** — `analyze_trade_n` (`src/trade/analyze_service.py:397-567@fae7209`). In `market_fairness`:
   - `team_context = False` (`:442`) and `include_capacity = False` (`:443`);
   - the posture resolver is the explicit no-op `_no_posture` (`:211-215`, `:445`);
   - no scarcity read (`:455-459`) and no comparables (`:503`);
   - each team is evaluated from ONE snapshot, with only its own legs applied.
4. **Per-team fairness** — `team_verdicts.team_fairness` (`src/trade/team_verdicts.py:169-209@fae7209`):
   - the asset evidence gates (`trade_decision.asset_evidence_gaps`) decide UNABLE;
   - otherwise the band the market lens already classified decides: `fair` → FAIR, anything else → NOT_FAIR
     (`:200`);
   - the band is **gross**: "not net of any forced-release cost, so it is identical in every mode" (`:12-16`).
5. **Band** — the market lens, `analyze_trade.equity_verdict` (`src/trade/analyze_trade.py:160-192@fae7209`):
   - canonical `rankDerivedValue` per asset, plus the active package model's adjustment
     (`package_model.adjusted_pair_totals`, `geom_q078_v1`);
   - then `fairness_bands.classify(gap, max(send_adj, recv_adj))` (`:174`) under `fairness_bands_v1` (PROVISIONAL:
     250 floor, cut points 3.5 / 9 / 18 %).
6. **Reduction** — `team_fairness_input` / `reduce_fairness` / `public_overall_state`
   (`src/trade/public_advisor.py:583-695, 753-760@fae7209`):
   - the reduction sees only `(rosterId, state, reasonCode, unavailable ids)`;
   - a non-`priced` engine row under FAIR / NOT_FAIR fails closed to UNABLE `evaluation_unavailable` (`:604-610`);
   - the engine's overall must equal the Kleene AND of its own per-team states (`:726-730`);
   - the published overall is the Kleene AND of the public per-team states, and it may never be more certain than
     the engine's (`:731-743`).
7. **Enforcement**:
   - Pydantic outbound models with `extra="forbid"`, `Literal` labels and no float type
     (`src/api/public_trade_advisor_api.py:263-400@fae7209`);
   - `assert_public_payload_safe`;
   - `assert_advisor_payload_value_free` (`src/trade/public_advisor.py:766-871@fae7209`): an int-key allowlist, no
     floats, a key blocklist that includes `value`, `gap`, `band`, `category`, `decision` and `fairness`, and fixed
     copy only.

The forced-release charge lives only in the private decision, `trade_decision._objective_value`
(`src/trade/trade_decision.py:482-520@fae7209`; the subtraction is at `:489-501`). The public path never reads
`decision`, `components`, `category` or `objectiveValue`, and `TeamFairnessInput` has no field that could carry them.

## 3. Findings table

"Affects public verdict?" means: can this input change the published FAIR / NOT FAIR / UNABLE for any team, or the
overall result.

| # | public path | input | affects public verdict? | evidence |
|---|---|---|---|---|
| F1 | 2 / 3 / 4-team | Team Context on/off | **No** | the mode is fixed to `market_fairness` (`public_advisor.py:716-718@fae7209`). Harness P1: 0 of 1,605 trades differ across `market_fairness`, `asset_only` and `team_context` |
| F2 | 2 / 3 / 4-team | competitive posture (PUSH / REBUILD / unavailable) | **No** | `_no_posture` (`analyze_service.py:211-215,445`). The harness P1 sweep covers three postures. Privacy test: `test_team_context_inputs_never_change_the_public_body` |
| F3 | 2 / 3 / 4-team | roster capacity, forced drops, **forced-release cost** | **No** | `include_capacity = False` (`:443`); `team_fairness` reads the gross band (`team_verdicts.py:189-200`). `test_market_fairness_writes_nothing_on_the_public_path` makes `build_capacity_context` raise. Harness, trade by trade: the per-trade public digest (sha256 over every trade's per-team results and overall) is identical at roster caps 3, 6 and 8, within v1 and within the v2 overlay (`digest_comparison_*.json`). Harness P6: forcing the private forced-release cost to 1e9 changes 0 public results while moving 184-449 private component-A levels per run |
| F4 | 2 / 3 / 4-team | roster utility / lineup lens / projections | **No** | `include_roster_utility = for_analysis and team_context` (`analyze_service.py:118`) is False. The privacy test sets projections to 0.1 ppg and gets an identical body |
| F5 | 2 / 3 / 4-team | team goal / strategy | **No** | `evaluate` passes no `team_goals`. Strategy enters only `decide`, which the public reduction never reads |
| F6 | 2 / 3 / 4-team | perspective team | **No** (validated only; it sets the default UI view) | `validate` checks membership (`public_advisor.py:547-551`). The parity test runs every perspective |
| F7 | 2 / 3 / 4-team | counterfactuals / comparables | **No** | `counterfactuals=False`. Comparables are skipped in `market_fairness` (`analyze_service.py:503`) |
| F8 | 2 / 3 / 4-team | fairness band | **Yes, by design** | `fairness_bands_v1` (PROVISIONAL); FAIR iff level `fair` (`team_verdicts.py:200`). The launch gate refuses until `approvedFairnessVersion` matches and the status is not PROVISIONAL (`public_trade_advisor_api.py:538-561`); `config/trade/public_advisor.json` has `approvedFairnessVersion: null` |
| F9 | 2 / 3 / 4-team | package model | **Yes, by design** | `geom_q078_v1` via `package_model.adjusted_pair_totals`. Any other model → `PackageModelUnavailable` → 503 `not_ready` |
| F10 | 2 / 3 / 4-team | missing / unpriced / off-board value | UNABLE `asset_not_evaluable` | evidence gates `off_board_assets`, `unpriced_assets`, `no_priced_assets`. A missing value is never treated as 0 (`trade_decision.asset_is_priced`) |
| F11 | 2 / 3 / 4-team | ownership (player held by several rosters, unknown pick ownership, rosters not current) | UNABLE `ownership_unverifiable`. A sent asset the sender doesn't own → 409 `stale_assets` | ledger `unverifiable_asset_ids` → the `ownershipEvidence` gate. The 409 never names the actual owner |
| F12 | 2 / 3 / 4-team | quarantined / stale value | UNABLE `evaluation_unavailable` (asset not named; F-1 open) | engine `valueState` (`analyze_service._value_entry`). Public fails closed (`public_advisor.py:566-610`); since `fae7209` this is an UNABLE answer, not a 503 |
| F13 | 2 / 3 / 4-team | engine invariant / conservation / admission | 503 `advisor_unavailable` (never a partial body) | `InvariantViolation` / `ConservationViolation` / `AdmissionRejected` → 503 |
| H1 | 2-team, **historical** (`5e5f8f453`..`2488f7557`, branch only) | Team Context, posture, capacity, forced-release cost | **Yes.** The old public category was `trade_decision.public_category_from_decision` over the full roster-aware decision | `2488f7557:src/trade/public_advisor.py:255` (`team_context=True`). Copy ran from `ACCEPT — STRONG TRADE FOR YOUR TEAM` to `DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE` (`2488f7557:src/trade/trade_decision.py:1500-1534`). Deleted at `2bbe5d4bd` |
| H2 | 3–4-team, **historical** | net band (`public_category_from_net_band`) | a different rule from H1: the inconsistency the owner asked about | `2488f7557:src/trade/trade_decision.py:1594`. Deleted at `2bbe5d4bd` |
| A1 | League Hub trade history (public, on `main`) | its own "Fair trade" grade | **A separate public fairness definition** | `src/public_league/trade_grading.py:54,66,196-217@aa88b5c`: `|pct| < 3.0` of the larger effective side, with no 250 floor. Differs from the advisor's band. Recorded as open owner decision **OD-F6** |

### 3.1 What the personalized path would have published (diagnostic D1)

On every trade the harness also runs the PRIVATE roster-aware decision (Team Context on, posture PUSH) and compares
it to the public market answer. Results on the synthetic league at `fae7209` (v1 bands).

**Denominator.** The last three columns count team results whose public answer is **FAIR** (146 at every cap). Every
one of them is bucketed by its private category, including teams whose private component A was never evaluated
because a roster-limit / execution gate decided the category first. "Explicit non-even" means `FAVORABLE`,
`UNFAVORABLE`, `STRONGLY_FAVORABLE` or `STRONGLY_UNFAVORABLE`; the remainder of "not even" is `UNAVAILABLE`.

| roster cap | team evaluations with a FAIR / NOT_FAIR public answer | private component A (net of forced release) disagrees with public | …because a forced release was charged | public FAIR: private category not `APPROXIMATELY_EVEN` | …of which explicit non-even | …of which `UNAVAILABLE` |
|---|---:|---:|---:|---:|---:|---:|
| 3 | 2,611 | 14 | 14 | **128 of 146** | 124 | 4 |
| 6 | 2,611 | 0 | 0 | **111 of 146** | 104 | 7 |
| 8 | 2,611 | 0 | 0 | **111 of 146** | 111 | 0 |

Where the 146 public-FAIR disagreements come from (`counts.D1_publicFair_byComponentA` in the evidence):

| roster cap | component A not evaluated (gate decided) | component A charged a forced release and left `fair` | component A `fair`, category moved by roster utility / strategy | agree (`APPROXIMATELY_EVEN`) |
|---|---:|---:|---:|---:|
| 3 | 84 (80 `UNFAVORABLE` `roster_limit`, 4 `UNAVAILABLE`) | 3 | 41 | 18 |
| 6 | 8 (1 `UNFAVORABLE` `roster_limit`, 7 `UNAVAILABLE`) | 0 | 103 | 35 |
| 8 | 0 | 0 | 111 | 35 |

The v2 overlay gives the same shape over its 144 public-FAIR teams: 126 / 109 / 109 not even at caps 3 / 6 / 8
(122 / 102 / 109 explicit non-even).

An earlier revision of this table skipped every team whose component A was not evaluated. That dropped 84 of the 146
public-FAIR teams at cap 3 and 8 at cap 6, and under-reported the disagreement (it read 44 of 62 and 103 of 138).

**Example at cap 3** (synthetic ids):
- A team at its cap receives two players for one. The market gap is about 1.2 % of the larger side, so the public
  answer is **FAIR** for both teams.
- The private component A charges the forced release and classifies the trade `lopsided`, so the private category is
  **STRONGLY_UNFAVORABLE**.
- That is the category the pre-`2bbe5d4bd` design mapped to "DECLINE — STRONGLY NOT RECOMMENDED".

These disagreements are the intended roster-aware behaviour of the private calculator and War Room. Only the 14
forced-release cases at cap 3 (3 of them on public-FAIR teams, 11 on public NOT_FAIR teams that the charge pulled into
the private `fair` band) inherit the forced-drop over-charge that Investigation A is fixing. At caps 6 and 8 no forced
release was charged, so all of the differences there come from the roster-limit / execution gates and from the
roster-utility and strategy components. At the current head none of them reaches the public answer.

## 4. Consistency verdict

**One authoritative public fairness calculation: YES at `fae7209b6b`.**

- **One code path for every team count:** `public_advisor.evaluate`, one engine call, one per-team rule and one
  Kleene AND.
- **N = 2 matches the private market band.** The result equals the gross band the private 2-team `/api/trade/analyze`
  market lens computes for each side
  (`tests/trade/test_public_advisor_parity.py::test_two_team_fair_equals_the_existing_war_room_market_band`).
- **Public = reduction of private** (spec invariant I11). The public result equals the private `fairness.state` in
  every private mode and from every perspective (`test_public_fairness_equals_the_private_engine_from_every_perspective`).
  The one fail-closed exception is the F2 withheld-value downgrade, which can only make a team less certain.
- **N = 2 symmetry** (spec I18): both teams always share a state.
  - Harness P3: verified on 1,485 two-team trades.
  - Pure math: on 20,000 random package pairs, swapping the sides never changes the band level, under both
    `fairness_bands_v1` and `fairness_bands_v2` (`bands_symmetry_v1.json`, `bands_symmetry_v2.json`).
- **Independent recomputation** (harness P4): every priced 2-team FAIR / NOT_FAIR equals the band owner's
  `classify(adjusted gap, band base)` recomputed from board values alone. There were 0 mismatches under v1 and under
  the v2 overlay, at roster caps 3, 6 and 8.
- **Harness scope.** P2 and P5 exercise `public_advisor.evaluate` and its result dataclass, not the HTTP route or the
  served body (`_safe_dump`). That the served body is value-free rests on the advisor's own privacy and contract tests
  and on `assert_advisor_payload_value_free`, which `_safe_dump` runs on every response.

The advisor-branch suites were run read-only at `fae7209`: `test_public_advisor_parity`,
`test_public_advisor_withheld_values`, `test_public_trade_advisor_privacy`, `test_public_trade_advisor_contract`,
`test_public_trade_advisor_validation`, `test_team_verdicts` and `test_analyze_multi_team`. Result: **3,262 passed,
6 skipped**.

## 5. Exposure check

| surface | numeric / proprietary content | verdict |
|---|---|---|
| analyze body | Ints appear only under `rosterId`, `perspectiveRosterId`, `from`, `to` and `teamCount`. Strings are fixed copy. `fairnessVersion` is a version string; `generation` is an opaque hash | clean |
| team / asset lists | Asset order is `position_alpha`: identity only, never value (`public_advisor.py:419-443`). Also carried: an `evaluable` boolean; pick `season` / `round` / `originRosterId`. Projection labels are OFF (OD-2) | clean (`evaluable=false` discloses "the board does not price this", not a number) |
| errors | fixed copy table (`public_advisor.py:138-182`), no exception text; the 409 never names the actual owner | clean |
| UI | Renders server labels verbatim and never receives a value (`frontend/app/league/sections/_advisor-result.jsx:1-15,145-148@105f074`). The copy says the result "doesn't consider any team's roster needs, lineup or plans". The bundle check's `FORBIDDEN_WORDS` regex rejects `accept / decline / approve / deny / reject / should / recommend* / advice / favorable / unfavorable / win / lose / smash / fleece / your roster / your lineup` in the advisor chunks' string literals (`frontend/scripts/check-public-bundle-privacy.mjs:78-79@105f074`). `fairnessVersion` is not rendered | clean |
| oracle | A deterministic binary answer lets a patient caller bound value ratios by bisection | **Residual, already accepted:** spec `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md` §6 ("slow, visible reconstruction (about 30k queries)") and design record `BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md` Part III item 6. The limiter priors are only speed bumps |

No `ACCEPT` / `DECLINE` / `FAVORABLE` vocabulary remains in public code on either advisor branch. Checked with
`git grep` over `src/`, `frontend/lib/trade-advisor.js` and `frontend/app/league` at both heads. The only
`*FAVORABLE*` constants left are the PRIVATE `team_verdicts.CATEGORIES`.

## 6. Changes the advisor lane needs

None is needed to meet the owner's intent at the current head. The following keep it true as the adjacent lanes land.

1. **Read FAIR from the band owner, not a literal (after #1886 merges).**
   - Change `src/trade/team_verdicts.py:200@fae7209` from `fair = level == "fair"` to
     `fair = fairness_bands.counts_as_fair_trade(level)`.
   - Why: OD-F1 puts the binary rule in `config/trade/fairness_bands.json::fairTradeLevels`, and the config says a
     public adapter reads it "from here, never a literal" (`19ec3f7:config/trade/fairness_bands.json`; helper at
     `19ec3f7:src/valuation_math/fairness_bands.py:243`).
   - Today both give `["fair"]`, so this is a single-owner fix, not a behaviour change.
2. **Stop publishing a band base the band no longer uses (private payload, after #1886).**
   - `src/trade/team_verdicts.py:193-199,206@fae7209` computes `largerAdjustedSide` from the adjusted totals.
   - Under v2 the band divides by the larger package utility instead. The private multi-team payload would then show
     a `relativePct` that cannot be reproduced from `gap / largerAdjustedSide`.
   - Measured on a scratch overlay of the v2 backend diff onto `fae7209`:
     `tests/trade/test_analyze_multi_team.py::test_i14_one_to_many_directional_numbers` reads
     `(610, 9610.0, 6.82, 'slight')` against an expected `6.35`.
   - Fix: read `largerPackageUtility` from the market lens detail, which v2 adds at
     `19ec3f7:src/trade/analyze_trade.py`. Private only; the public body never carries this field.
3. **Regenerate the contract fixtures when v2 lands.**
   - On the same overlay, six `tests/api/test_public_trade_advisor_contract.py` fixture cases fail, only because
     `fairnessVersion` reads `fairness_bands_v2` instead of `fairness_bands_v1`.
   - Every public-verdict, parity, privacy and validation test passed (overlay run: 3,253 passed, 9 failed = these 6
     plus the 3 in §6.2).
   - Regenerate with `python -m tests.api.trade_advisor_support`.
4. **Bring the frontend branch to the backend head before the release train.**
   - `advisor-hub-frontend@105f074` merged the backend at `82ca5fa984`; neither `c5dfa95` nor `fae7209` is in it.
   - The public body shape did not change in between, and `105f074` now renders `busy` / `timeout`.
   - The train must still be validated as one tree.
   - `ADMISSION_COPY` (`frontend/lib/trade-advisor-client.js@105f074`) is a verbatim client copy of server text and
     needs to stay in lockstep with `public_advisor.ERROR_MESSAGES`.
5. **Docs.**
   - When v2 lands, Part 0 step 3 of `BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md` ("the band `fairness_bands_v1`
     classified for that team's OWN adjusted package totals") should name v2 and its utility base.
   - The research memo §10 should carry an erratum: the advisor has been fairness-only since `2bbe5d4bd`. This is
     for the research lane, not the advisor lane.

**Not to change in the advisor lane:** `config/trade/public_advisor.json::approvedFairnessVersion` stays `null` until
the owner sets it. §5 of the owner record forbids activating or modifying the public threshold independently. The
launch gate (`public_trade_advisor_api.py:548-551@fae7209`) is what keeps the advisor dark until then.

## 7. Tests that would pin "one authoritative public fairness calculation"

Already present at `fae7209`; keep them blocking:

- I11 parity, from every perspective and in every private mode:
  `test_public_fairness_equals_the_private_engine_from_every_perspective`.
- N = 2 equals the private market band: `test_two_team_fair_equals_the_existing_war_room_market_band`.
- I18: `test_two_team_states_are_always_equal`.
- One engine call, in `market_fairness`, with counterfactuals off: `test_evaluate_is_the_reduction_of_analyze_trade_n`.
- Team-Context invariance (posture, projections): `test_team_context_inputs_never_change_the_public_body`.
- Capacity, utility and posture are never computed: `test_market_fairness_writes_nothing_on_the_public_path`.
- Value-free bodies: `assert_advisor_payload_value_free` on every response, plus the frontend bundle copy rule.

Recommended additions (small):

1. **Roster-cap sweep.** The same trades under registry `rosterSize` 3 / 6 / large give byte-identical public bodies.
   The harness shows this holds, but nothing pins it end to end if the capacity-never-computed guard is ever relaxed.
2. **Forced-release sentinel.** Monkeypatch `roster_capacity.ForcedDrop.release_cost` (or `forced_drop_cost`) to a
   huge value and assert the public body is unchanged. This guards the exact defect class Investigation A is fixing.
3. **AST guard on the public module.** `src/trade/public_advisor.py` must not reference `decision`, `components`,
   `objectiveValue`, `forcedReleaseCost`, `team_category`, `rosterCapacity` or `competitive_posture`. The existing
   AST guard covers only value-state names.
4. **Band-owner rule (after #1886).** Public FAIR ⇔ `fairness_bands.counts_as_fair_trade(level)`. A monkeypatched
   `FAIR_TRADE_LEVELS` proves the public answer follows the config (OD-F1).
5. **Band-base symmetry property.** For random package pairs, `classify(gap, base)` does not change when the sides
   are swapped, under the active band owner. This is the pure-math half of I18, so a future denominator change cannot
   silently break it.
6. **Cross-surface public "fair" registry (after OD-F6).** Any public label reading "fair" is produced by
   `fairness_bands`. By design this fails today on `src/public_league/trade_grading.py`, until the owner decides OD-F6.

`scripts/public_fairness_audit.py` (this branch) is a runnable differential harness over the advisor lane's own
synthetic league. It already covers three of these in harness form:

- item 1 — per trade, through `publicDigest` compared across roster caps (`--compare-digests`);
- item 2 — the P6 forced-release sentinel;
- item 5 — the `--bands-root` swap check (plus P3 over `public_advisor.evaluate`).

Items 3, 4 and 6 are not covered by the harness.

## 8. Interaction with `fairness_bands_v2` (#1886)

| item | state |
|---|---|
| OD-F1: FAIR TRADE = band `fair` only; overall FAIR iff every team is FAIR | **Approved.** The advisor already behaves this way, through a literal (see §6.1) |
| OD-F2: denominator = larger package utility | **Approved.** It flows into the public answer automatically through the market lens; a 1-for-1 is unchanged. On the synthetic league, public FAIR team results move from 146 to 144 (overlay runs, at every roster cap) |
| OD-F3 / OD-F5: publish v2 as an owner-approved prior; keep the 250 floor | **Approved.** The status is `PRIOR_OWNER_APPROVED_2026-10-20`, not `PROVISIONAL`, so the launch gate's provisional check would pass |
| OD-F4: post-launch validation against at-the-time market trades | **Pending** (`postLaunchValidation.state: PENDING`) |
| OD-F6: align or relabel the League Hub trade-history "Fair trade" grade | **Open** (see A1) |
| `approvedFairnessVersion` in `config/trade/public_advisor.json` | **Owner-only.** `null` today; no lane may set it |
| final public launch approval, OD-3 source permission, response floor, admission sizes, F-1 | **Open** |

Merging #1886 does not make the advisor serve. The launch gate still requires `approvedFairnessVersion`, a measured
`responseFloorMs` and a valid OD-3 record.

The two branches compose cleanly on the backend: the v2 diff applied to `fae7209` with line offsets only. The only
breakages are the expected fixture and private-field items in §6.2 and §6.3.

## 9. Risks

1. **Two public "fair" definitions** (A1 / OD-F6).
   - The League Hub trade-history grade calls a trade "Fair trade" below 3.0 %, with no floor.
   - The advisor uses 3.5 % with a 250-point floor: of the larger adjusted side under v1, of the larger package
     utility under v2.
   - The same trade can read "Fair trade" in one tab and NOT FAIR in the other, or the reverse for small packages.
     Owner decision OD-F6 is the gate.
2. **Neutral by design means roster-blind.**
   - A public FAIR can coexist with a private "can't fit your roster". That separation is intended, and the UI note
     states it.
   - Low-value filler sweeteners also move the public answer unmitigated (research memo §4). The approved remedy is
     the R-C informational disclosure, not a threshold or value change.
3. **Oracle reconstruction** (an accepted residual; see §5).
4. **Private payload drift after v2** (§6.2): a reader of the private multi-team payload could not reproduce
   `relativePct`.
5. **Regression risk if a future change re-threads Team Context.** The engine is shared and `mode` is the only switch.
   Recommended tests 1-3 make such a change fail loudly.

## 10. Recommendations

1. **Accept the current advisor design as meeting §5:** fairness-only, one calculation at every N, no numbers
   exposed, subject to the existing launch gates.
2. **Do not reintroduce** Team Context, posture, capacity or forced-release cost into any public path. The private
   calculator and War Room keep them, and the forced-drop correction (Investigation A) stays a private-surface fix.
3. Land §6.1-6.3 in the advisor lane, in the same train as #1886 or immediately after it.
4. Add the recommended tests §7.1-7.3 now (they need no owner decision), and §7.4-7.5 with #1886.
5. Ask the owner to decide **OD-F6**, so the public site has one meaning of "fair".
6. Leave `approvedFairnessVersion` at `null` until the owner sets it.

## 11. Method and limits

- **Code reads:** at the exact SHAs in §1, via `git show` / `git archive` into a scratch directory. Nothing was checked
  out over the audited branches and nothing was pushed to them.
- **Harness:** `scripts/public_fairness_audit.py --code-root <read-only checkout of the advisor head>`, over the
  advisor lane's own synthetic four-team league (`tests/api/trade_advisor_support.py`; no real league data).
  - Trades: every 1-for-1, 2-for-1 and 1-for-2 between every pair of teams (1,485 two-team trades), plus 60 random
    3-team and 60 random 4-team ring trades. Seed `20261020`; roster caps 3, 6 and 8, each under v1 and under the v2
    overlay.
  - Checks P1-P5 as described in the script, plus **P6**, a forced-release sentinel. It replays every trade with
    `trade_decision._objective_value` charging a 1e9 forced-release cost on every team, and with
    `RosterCapacity.to_dict` reporting 1e9. It requires 0 public changes, and at least one moved private component-A
    level to prove the sentinel is live.
  - Every run emits `publicDigest`: sha256 of the ordered `(trade index, shape, per-team public results, overall)`
    list. `--compare-digests` asserts equality over saved runs. Results:
    - v1 caps 3/6/8: `5f2002b3c71cfae5…`, identical (`digest_comparison_v1.json`);
    - v2 overlay caps 3/6/8: `8501804266dd9670…`, identical (`digest_comparison_v2_overlay.json`);
    - each run's digest under the P6 sentinel equals its own `publicDigest`;
    - v1 vs v2 differ, as expected (146 → 144 public FAIR).
  - **Scope:** P2 and P5 run over `public_advisor.evaluate` and its dataclass, not the HTTP route or the served body
    (`_safe_dump`). That the body is value-free rests on the advisor's own privacy tests and on
    `assert_advisor_payload_value_free`.
  - Evidence is in `docs/trade/evidence/public_fairness_audit_2026-10-20/`. `--bands-root` runs the pure-math swap
    check.
- **v2 composition:** measured on a scratch overlay of the v2 **backend** diff (`config/` and `src/` from
  `1332aba1c6..19ec3f7394`) onto `fae7209`. The JS mirror and the frontend half of v2 were not combined.
- **Limits:**
  - synthetic league only (4 teams, 16 players, 8 picks);
  - in the harness, the private `team_context` runs tried live Sleeper calls for the synthetic league id and fell
    back. This happens in private modes only; `test_market_fairness_writes_nothing_on_the_public_path` pins the public
    mode to touch nothing;
  - no production or box data was read.

## 12. Independent review

An independent review returned **ACCEPT WITH FIXES**: the public path is consistent with owner §5, and the defects were
in the diagnostic evidence and its wording.

The reviewer independently confirmed, at `fae7209`:
- there is one public route, `post_trade_advisor_analyze` (`src/api/public_trade_advisor_api.py:878-879`);
- its request model is `extra="forbid"` (`AdvisorAnalyzeRequest`, `:239-245`);
- `public_advisor.evaluate` makes a single `analyze_trade_n(mode="market_fairness")` call (`public_advisor.py:716`);
- every response passes the value-free payload assertion (`_safe_dump`, `:411-416`);
- the advisor suites gave 3,268 passed in the reviewer's environment, against 3,262 passed and 6 skipped in the
  author's.

Fixes applied in this revision:
1. §3.1 now buckets the private category for every public-FAIR team, and defines the denominator. The harness used to
   skip teams whose component A was not evaluated.
2. Cross-cap identity now rests on a per-trade digest, not equal totals. The P6 forced-release sentinel was added; §7
   now names exactly which recommended tests the harness covers.
3. The forced-drop over-charge is attributed only to the 14 cap-3 cases.
4. The harness scope (evaluator, not route or served body) is stated in §4 and §11. Dead posture save/restore code was
   removed.
5. §5 lists the full forbidden-word set and cites `:78-79`.

STATUS: DONE
ACCEPTANCE: audit the public 2/3/4-team paths against owner §5; findings table; consistency verdict; exposure check;
advisor-lane changes with file:line; pinning tests; v2 interaction; risks; recommendations.
EVIDENCE: code reads at the §1 SHAs; advisor suites at `fae7209` (3,262 passed, 6 skipped, read-only; 3,268 passed in
the independent reviewer's environment); harness P1-P6 0 violations at caps 3/6/8 under v1 and under the v2 overlay;
per-trade public digests identical across caps (and under the forced-release sentinel) for v1 and for v2; band swap
symmetry 0 / 20,000 under v1 and v2; v2 overlay suite run (3,253 passed, 9 expected failures named in §6.2-6.3).
UNRESOLVED: OD-F6 (owner); validating the frontend train as one tree with the backend head (integration); the research
memo §10 erratum (research lane).
BLOCKERS: none for this audit.
NEXT_ACTION: the advisor lane applies §6.1-6.3 with #1886 and adds tests §7.1-7.3.

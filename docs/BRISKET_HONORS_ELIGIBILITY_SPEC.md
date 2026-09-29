# Brisket Honors — MVP / Manager Eligibility Rules

> **OWNER CORRECTION — 2026-09-29 (binding; immediate; supersedes the record half of every rule below).**
> For any award that actually has a record eligibility requirement, **.500 OR BETTER qualifies**: official
> regular-season winning percentage **>= .500** under the league's canonical standings semantics (a tie counts
> as half a win). **Exactly .500 counts** (6-6, 7-7, 8-8 qualify); below .500 does not (6-7, 7-8). Every earlier
> statement in this file that a franchise must be "above .500", "strictly greater than .500", or that "a .500
> record is not a winning record" is **SUPERSEDED** and kept only for provenance. Today the only award with a
> record requirement is **League MVP**; its separate playoff-field requirement is **unchanged** (in the field +
> .500 or better = eligible; outside the field = ineligible regardless of record). A franchise with no decisions
> never qualifies from a fabricated .500; unverifiable standings stay UNVERIFIED. Implemented in
> `src/public_league/awards.py::_league_mvp_gate` (`2*wins + ties >= games`, `games > 0`; ineligibility reason
> `team_record_below_500`, which replaced `team_record_not_above_500`; a franchise with no decided games is
> `team_record_unavailable`, never "below .500"). No published League MVP winner changed (2024/2025 finalized; the
> 2026 live leader unchanged, both live leagues; replay 2026-09-29); live race membership widens as intended.
>
> **Manager of the Year has NO record or playoff gate.** The owner's unified Manager of the Year direction
> (one combined award; no separate GM award; no playoff-qualification requirement; no winning-record requirement;
> a manager below .500 may win) supersedes this file's §8 Manager eligibility rules and the note below that said
> "Manager of the Year is NOT superseded". Recorded in `docs/OWNER_REQUESTED_TODO.md` ("Owner correction — award
> record eligibility is .500 OR BETTER", 2026-09-29), where the owner restated it. The unified method itself is a validation track (PR #1513), not a
> promoted award; `main`'s current Manager of the Year composite has no eligibility gate.

> **OWNER DECISION — 2026-09-26 (binding; supersedes the 2026-08-14 amendment below).** League MVP
> **requires meaningful team success**: this document's §3 (live) and §4 (finalized) gate is the canonical rule
> again — the credited franchise must be in the championship playoff field **and** ~~above .500~~ .500 or better (record half corrected 2026-09-29). Offensive and
> Defensive Player of the Year, both Rookie of the Year awards and the positional awards **do not** inherit it
> (§10, §14). League MVP = elite player performance on a successful fantasy team; OPOY / DPOY = the best
> offensive / defensive individual performance regardless of the fantasy team's record. Implemented in
> `src/public_league/awards.py` (`_league_mvp_gate`); the implementation status is recorded in §14.
>
> ~~**RECONCILIATION AMENDMENT — 2026-08-14.**~~ *Superseded 2026-09-26.* It had promoted this file from PR #809
> with one binding supersession — "player MVP has no hard playoff-field or >.500 eligibility gate", citing
> `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §7 — which the owner reversed on 2026-09-26. Kept for provenance only.
>
> ~~**Manager of the Year is NOT superseded.** It may retain an appropriately validated team-success eligibility
> rule, exactly as this document states. GM/Executive and player-performance awards stay conceptually separate.
> No newer owner instruction touches MOTY, so this document remains canonical for it.~~ *Superseded by the
> owner's unified Manager of the Year direction (no playoff or record gate; see the 2026-09-29 banner above).*


**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** Brisket Honors / Awards / Public League History  
**Execution posture:** APPROVED PRODUCT REQUIREMENT; IMPLEMENT WITH THE BRISKET HONORS / HISTORICAL-TRUTH WORK, NOT AS AN INTERRUPTION TO CURRENT B6/B7 FOUNDATION WORK  
**Public/private posture:** PUBLIC-SAFE awards methodology and results, subject to historical-data coverage/provenance.

---

## 1. Owner intent

The fantasy-league **Most Valuable Player** should not simply be the player with the largest raw or VORP total regardless of whether that production meaningfully contributed to a competitive team.

For League MVP specifically, meaningful team success is an eligibility requirement:

> A player should only be in the MVP race when the fantasy team receiving that player's credited contribution is both **currently in a championship-playoff qualifying position** and has a **.500-or-better record** under the league's actual standings rules. *(Record wording corrected 2026-09-29; originally "a winning record".)*

~~The same basic competitive-success gate should apply to **Manager of the Year** (or an equivalent future Coach of the Year award if that is ever separately approved), because that award is explicitly about competition performance.~~ *Superseded: unified Manager of the Year has no playoff or record gate.*

The gate should **not** automatically apply to GM of the Year, OPOY/DPOY, rookie awards, positional awards, or other honors whose purpose is different.

---

## 2. Preserve the canonical MVP performance method

This eligibility rule is a **gate**, not a replacement scoring formula.

The approved Brisket Honors player-performance foundation remains **Realized Lineup VORP**:

- actual fantasy starts only;
- bench-only production receives no lineup contribution credit;
- player fantasy points minus the positional replacement expectation for that starting opportunity;
- negative contributions remain negative;
- scoring/replacement expectations are season-, league-, lineup-, and scoring-format-specific;
- Playoff MVP remains a separate postseason award.

Eligibility answers **who is allowed into the League MVP race**. Realized Lineup VORP or its later validated canonical successor answers **how eligible players are ranked**.

Do not replace the eligibility gate with raw points, dynasty value, ROS value, popularity, or a subjective narrative score.

---

## 3. League MVP eligibility — live season

Use the latest **completed/finalized scoring period**, not an in-progress Sunday scoreboard, to determine eligibility.

A player-franchise contribution is MVP-eligible only when that fantasy franchise satisfies BOTH:

1. **Current playoff-field requirement:** the franchise is currently in a seed/position that would qualify for the league's championship playoff field under the league's actual qualification rules if the regular season ended at that completed scoring period; AND
2. **Record requirement (.500 or better):** the franchise's official regular-season winning percentage is **greater than or equal to .500** under the league's actual standings system. A .500 record satisfies the record requirement.

~~2. Winning-record requirement: strictly greater than .500. A .500 record is not a winning record.~~ *Superseded 2026-09-29 by the owner correction above.*

Do not define the playoff field as a fixed top-N percentage of teams. Derive it from the requested league's actual configuration and qualification rules.

Do not use the canonical Playoff Predictor's probability as the eligibility gate. Projected playoff probability may be displayed as context, but award eligibility should not depend on another predictive model.

If no candidate satisfies both conditions, report the live League MVP race as **NO ELIGIBLE CANDIDATE / RACE NOT CURRENTLY ACTIVE** rather than silently widening the field.

The UI should be able to say why an otherwise high-scoring player is not currently eligible, e.g. `Team outside current playoff field` or `Team record is below .500`. A .500 team must never receive the below-.500 reason.

---

## 4. League MVP eligibility — finalized season

For the finalized League MVP award, a player-franchise contribution is eligible only if the associated fantasy franchise:

1. **actually qualified for the championship playoffs**, using the finalized season's real bracket/qualification result; AND
2. finished the regular season with an official winning percentage **greater than or equal to .500** (.500 or better; exactly .500 counts — corrected 2026-09-29 from "strictly greater than .500").

The final award must not substitute a late-season projection for actual qualification.

League MVP remains fundamentally a **regular-season player award** unless a future owner decision explicitly changes that. Postseason player performance belongs in the separate Playoff MVP / Championship MVP family and must not silently inflate League MVP.

---

## 5. The record requirement must follow host standings semantics

The record requirement (".500 or better"; this section previously said "winning record") means the league's actual official standings performance, not simply head-to-head wins divided by weeks.

For leagues with an extra weekly result against the league median/all-play threshold:

- include the host's median-game results exactly as the official standings do;
- do not calculate the eligibility record from H2H games alone;
- do not double-count median results if the host's stored W/L record already includes them.

For leagues with ties or standings points, derive an equivalent official winning percentage/competition rate that reproduces host standings. A simple default may conceptually be `(wins + 0.5 * ties) / total decisions`, but the implementation must verify the host semantics rather than hard-code that formula for every league.

If standings semantics cannot be verified, eligibility is **UNVERIFIED / UNAVAILABLE**, not `false` and not an assumed conventional record.

This rule consumes the same canonical standings-rule interpretation as the Playoff Predictor. Do not build a second league-format parser inside Brisket Honors.

---

## 6. Current playoff position must use real qualification rules

`currently in a playoff position` must reproduce the requested league's real championship-playoff qualification logic, including where applicable:

- number of playoff berths;
- divisions/division winners;
- wild cards;
- tiebreakers;
- league-median/all-play results;
- any other host rule that changes current seeding or qualification.

For the owner's primary league, current evidence/owner confirmation establishes a 12-team league with **7 championship playoff berths**, **one #1-seed bye**, and league-median standings enabled. Those facts are a regression fixture for that league, not a universal awards assumption.

---

## 7. Player trades / multiple fantasy franchises

A player can contribute to multiple fantasy franchises in one season because of trades, waivers, reacquisition, or other roster movement.

Do **not** attach the player's entire season contribution to whichever fantasy manager happens to roster him at the end of the year.

Track Realized Lineup VORP at the player-franchise-week level so contribution remains attached to the fantasy team that actually started/received it.

For League MVP eligibility/ranking:

- contribution accrued for an **eligible** fantasy franchise may count toward the player's MVP case;
- contribution accrued for a franchise that fails the MVP team-success gate does not become eligible merely because the player was later traded to a playoff team;
- if a player materially contributes to more than one eligible franchise, those eligible contributions may be combined for the player-level MVP score, with franchise provenance preserved;
- historical display should make multi-franchise seasons understandable rather than rewriting ownership history.

This prevents a late trade from laundering an entire season of production from a noncompetitive team into an MVP-eligible campaign.

---

## 8. Manager of the Year eligibility — SUPERSEDED

> **Superseded by the owner's unified Manager of the Year direction:** one combined award, no separate GM award,
> **no playoff-qualification requirement and no record requirement** — a manager below .500 may win if the complete
> formula ranks them first. The unified method is a validation track (PR #1513), not a promoted award. The text
> below is kept for provenance only and is not an active rule.

~~Manager of the Year is a **competition-performance** award and should use the same baseline team-success eligibility gate:~~

### Live race
A manager is eligible only when, as of the latest finalized scoring period, the manager's team:

- occupies a current championship-playoff qualifying position; AND
- has an official winning percentage above .500.

### Final award
A manager is eligible only when the team:

- actually makes the championship playoffs; AND
- finishes the regular season with a winning record.

The eligibility gate does not replace the approved Manager of the Year scoring framework. Among eligible managers, the current exploratory framework remains:

- 30% all-play / schedule-independent performance;
- 25% Team VORP;
- 20% final/playoff achievement;
- 15% consistency;
- 10% close/high-leverage performance.

Those weights remain subject to the already-required 2024/2025 replay, sensitivity, and correlation analysis before finalization.

Do not double-count the eligibility condition as a large extra bonus inside the composite unless historical validation/owner approval establishes a reason.

---

## 9. GM of the Year — deliberately NO playoff/winning-record gate

> **Superseded as a separate award** by the unified Manager of the Year direction (GM-style roster/asset
> metrics become inputs to the one combined award, which also has no playoff or record gate). Kept for provenance.

GM of the Year measures **roster construction / asset management**, not simply whether the current team won games.

A rebuilding manager can have an excellent GM season by improving the roster, acquiring picks, drafting well, winning trades, adding waiver value, or increasing future expected strength while intentionally sacrificing present-season wins.

Therefore GM of the Year should **not require**:

- a winning record;
- current playoff position;
- final playoff qualification.

The approved GM of the Year framework remains conceptually separate:

- 30% Trade Acquisition VA;
- 25% Waiver/FA VA;
- 20% Draft VA;
- 15% Net Roster Improvement;
- 10% Acquisition Efficiency/Depth.

Those weights are exploratory and require historical replay/validation.

Preserve the firewall:

> **Manager of the Year = competition management.**  
> **GM of the Year = roster/asset building.**

Do not let the MVP/Manager playoff gate erase that distinction.

---

## 10. Awards that do NOT inherit this gate by default

Do not automatically require a winning/playoff team for:

- Offensive Player of the Year / offensive MVP if retained as a distinct award;
- Defensive Player of the Year / defensive MVP;
- Offensive Rookie of the Year;
- Defensive Rookie of the Year;
- positional awards / All-Brisket team selections;
- Points King;
- Top Offense / Top Defense;
- waiver/trade/rebuild awards unless their own canonical methodology says otherwise;
- other objective/statistical honors.

A great WR, LB, rookie, or positional performer can deserve recognition on a bad fantasy team. The League MVP distinction is intentionally more tied to winning.

Playoff/Championship MVP already has its own postseason-team eligibility and should not be redefined by this document.

---

## 11. Live race UX

For live League MVP and Manager of the Year races:

- calculate eligibility from the latest finalized standings snapshot;
- display the as-of week/date;
- rank only eligible candidates in the primary race;
- optionally show a compact `Outside the race` / `Not currently eligible` context for exceptional performers who fail the team-success gate, but do not rank them as eligible finalists;
- do not constantly flicker eligibility from partial/in-progress weekly scores;
- do not use playoff odds as a secret eligibility threshold.

If an eligible team falls out of the playoff field or below .500 after a finalized week, its candidate leaves the active League MVP race until eligibility is regained (a team at exactly .500 stays eligible on record; corrected 2026-09-29). Manager of the Year has no such gate.

---

## 12. Historical replay

Apply the same eligibility methodology retroactively to 2024, 2025, and future completed seasons when the underlying league history is sufficiently reconstructable.

For each season preserve:

- exact league playoff structure;
- official standings/median-game rules;
- final regular-season record;
- actual playoff qualification;
- player-franchise-week starting contribution;
- eligibility state and reason;
- Realized Lineup VORP methodology/version;
- data coverage/provenance.

Do not manufacture historical MVP eligibility if the standings, starts, scoring, or playoff structure cannot be reconstructed reliably. Mark the award/race component `UNAVAILABLE` or `PARTIAL` as appropriate.

Use the same inaugural 2026 methodology for retroactive 2024/2025 Brisket Honors once validated; do not create easier historical rules simply because older data is harder to obtain.

---

## 13. Validation / acceptance criteria

Before this eligibility system is considered complete:

1. derive playoff-qualification and record semantics from the canonical league-settings/standings owner rather than hard-coding team counts;
2. test a normal H2H league and a league-median league;
3. prove a player on a .500 team **is** eligible on record and a player on a below-.500 team is not (corrected 2026-09-29; originally "prove a player on a .500 team is not League MVP eligible");
4. prove a player on a winning team outside the current playoff field is not live MVP eligible;
5. prove a player on an in-field winning team is eligible;
6. prove final MVP eligibility uses actual playoff qualification rather than predicted probability;
7. test a traded player whose VORP spans eligible and ineligible fantasy franchises and prove contribution is attributed correctly;
8. ~~prove Manager of the Year uses the competition-success eligibility gate;~~ superseded — prove unified Manager of the Year has **no** record or playoff gate (a below-.500 manager is not excluded);
9. prove GM-style metrics do **not** inherit the gate;
10. prove OPOY/DPOY/ROY/positional awards do not silently inherit it;
11. verify median-game records are not omitted or double-counted;
12. verify live races use latest finalized week rather than partial current-week standings;
13. replay at least 2024/2025 where coverage permits and document unavailable/partial evidence honestly;
14. run broader awards/public-contract/frontend/E2E gates before activation.

---

## 14. Method status

**League MVP team-success eligibility:** OWNER-APPROVED / FINAL DIRECTION (re-confirmed 2026-09-26). **Implemented 2026-09-26** in
`src/public_league/awards.py::_league_mvp_gate` for live (§3: canonical standings order × the league's own
`playoff_teams`, host records incl. median games, .500 or better since the 2026-09-29 correction — previously strictly above .500) and finalized seasons (§4: actual winners-
bracket membership + final record); unverifiable fields report `mvp_eligibility_unverified`, an empty eligible
pool reports `no_eligible_mvp_candidate`, and the race publishes the best performers kept out with the reason
(§11). **Partial:** §7's per-franchise-week attribution for traded players is not yet implemented — a player is
credited to his most recent franchise (the existing award attribution) and gated on it.  
**Manager of the Year team-success eligibility:** ~~OWNER-APPROVED / FINAL DIRECTION.~~ SUPERSEDED — unified Manager of the Year has no playoff or record gate.  
**GM of the Year playoff/winning-record gate:** EXPLICITLY NOT APPLIED.  
**OPOY/DPOY/ROY/positional playoff/winning-record gate:** EXPLICITLY NOT APPLIED BY DEFAULT.  
**Realized Lineup VORP player-performance foundation:** APPROVED CANONICAL DIRECTION, subject to historical-truth/coverage validation.  
**Manager/GM exact composite weights:** EXPLORATORY / REQUIRE HISTORICAL REPLAY AND SENSITIVITY VALIDATION.

---

## Owner season-scoped award eligibility overrides (2026-09-26)

An owner competition rule can bar a named manager from **winning one award in one season**. It is an
eligibility rule, not a measurement rule: the award's canonical metric is still computed, ranked and
published for that manager (metric rank, value, and a public label), and the award goes to the
highest-ranked eligible candidate.

- **Record:** `config/leagues/award_eligibility_overrides.json` — season, that season's Sleeper league id,
  award key, canonical owner ids, rule type `owner_season_eligibility_override`, who decided, when, why.
- **Owner:** `src/public_league/award_eligibility.py` — the only reader; a malformed rule fails loudly.
- **Scope:** season + league id, never a clock. A new season starts with no rule; a past season keeps its
  rule when viewed later.

| season | award | ineligible owners | reason |
|---|---|---|---|
| 2026 | `waiver_king` | `712035316776669184` (Joel), `1303549304882892800` (Blaine) | owner competition rule for 2026 |

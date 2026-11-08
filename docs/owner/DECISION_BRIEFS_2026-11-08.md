# Owner decision briefs, 2026-11-08

Part 29 of the unified directive (`docs/owner/UNIFIED_ENGINEERING_FORECASTING_DIRECTIVE_2026-11-08.md`, intake MD-117).
These are the decisions that cannot be made under delegated engineering authority. Nothing here is decided or activated.
The canonical decision record stays `docs/owner/OWNER_DECISION_REGISTER.md`; once you decide, the outcome goes there.

Silence is not a decision. Every item keeps its current behavior until you answer.

## 1. Best-ball playoff odds: activate the ROS flag, or run a new study

- **Current rule:** the simulator serves `rosValue/2.7` from a fallback model, multiplied by `(1 + 0.2z)`. Flag
  `playoff_ros_counted_once` is off. `ODR-PLAYOFF-ROS-DOUBLE` approves removal as policy, only through a passing
  preregistered comparison.
- **Evidence:** #2161, holdout weeks 5–8, 48 team-weeks. CRPS 69.0 against 29–32 for every simple challenger. MAE 81.8
  against 42–45. Predicted spread between teams is 1.83× realized. 43 of 72 binary outcomes sit at ≤1% or ≥99%, 4 of them
  wrong. Team order is sound (concordance 0.814, the best of all arms). Two separate faults: the ROS multiplier drives
  spread, and the through-origin `/2.7` drives level. The flag alone fixes spread (ratio 1.01) but leaves bias at +69 points.
- **Alternatives:** (a) activate the flag now; (b) preregister a new study on weeks 9 onward, testing a fitted affine
  conversion together with counting ROS once; (c) keep the incumbent and only label the output.
- **Recommendation: (b).** The flag failed gate G4 on 2026-10-18, and fixes only half the fault. The new study must
  repair the gate-design flaw disclosed in #2161 before it sees any data, without changing the completed experiment.
- **Risk:** live odds shift when anything changes. Until then, users see odds that are known to be overconfident.
- **Uncertain:** only 8 weeks exist, and the same weeks both fit and test unless the study waits for new ones.
- **Authorization needed:** approve the study (and later, any activation). **Can proceed without you:** study design and harness.

## 2. PR #1938: IDP scoring corrections

- **Current rule:** unmerged. The nflverse scoring path matches the host within 0.01 on 91.6% of comparable player-weeks.
- **Evidence:** taxonomy in `docs/league-intelligence/SCORING_PARITY_TAXONOMY_2026-11-08.md`. #1938 raises parity to
  96.2% and fixes all 137 implementation-error rows. It does not touch the market board; it changes BDVM realized PPG, so
  Fund gap, `/api/bdvm/*`, the Draft BDVM panel and signal alerts move.
- **Alternatives:** (a) merge as a unit; (b) merge without the special-teams tackle rule; (c) hold.
- **Recommendation: (a), after sizing it.** Run `pr1938_bdvm_value_impact.py` on the box snapshot first, and decide the
  special-teams tackle rule knowingly: 62 rows, the only part that changes IDP-listed values.
- **Risk:** BDVM values move. Rollback is a revert and restart, with no migration.
- **Uncertain:** value-level movement, which needs the box snapshot.
- **Authorization needed:** merge. **Can proceed:** the impact script, once run on the box.

## 3. Division title payout tiebreaker

- **Current rule:** unconfirmed, so ties are reported rather than resolved (#2158). Live example: Brent 64% outright, 36% tied.
- **Evidence:** your playoff rules state divisions decide schedule and a separate payout. No record says what breaks a tie for that payout.
- **Alternatives:** points for; head-to-head; split the payout. **Recommendation:** none. This is a league fact only you know.
- **Authorization needed:** state the rule. **Can proceed:** everything else; ties stay labelled.

## 4. Median-game wins in rookie draft order

- **Current rule:** reverse head-to-head record, then lower points for (`src/public_league/draft_order.py`), marked provisional.
- **Evidence:** `dynasty_main` counts a weekly median game in official standings, and the forecast uses head-to-head only (`docs/picks/DRAFT_ORDER_RULE.md`). No completed snake draft has settled which applies, because the 2026 rookie draft was an auction.
- **Alternatives:** count median wins, or not. **Recommendation:** none. This is a league rule, and it has a deadline: the 2027 draft order at season end.
- **Authorization needed:** state the rule. **Can proceed:** forecasts stay labelled provisional.

## 5. Hill curve independent validation target

- **Current rule:** the served champion is v2. Automatic promotion is blocked (`no_independent_validation_target`); the registry is deliberately empty.
- **Evidence:** `docs/valuation/methodology_proposals/W30_F008_HILL_DENOMINATOR.md`. The code defect is already fixed, and the
  served constants still carry it. A denominator-corrected curve (C0) beats the incumbent on 102 of 102 forward days of
  holdout markets, but installed into today's blend it makes the board worse: discarded KTC or IDPTC votes on offense rows
  go from 14 to 186, and ordering worsens in 23 of 23 forward pairs. The routine refit (v302) would drop value-direct votes on 275 offense rows.
- **Real question:** what scale should the translation curve target? Fitting six value boards and matching the blend's
  value-direct voters are different goals, and no candidate wins on both.
- **Alternatives:** (a) register a target built on realized fantasy scoring; (b) register a target built on the
  completed-trade ledger, which needs its own preregistration and KTC-excluded provenance; (c) keep v2 and leave promotion blocked.
- **Recommendation:** keep v2 served, approve the offline shadow evaluation of C0 and C_vd, and define target (a) first. It shares no data with the KTC-family training boards.
- **Risk:** a target chosen after seeing candidates is target shopping, so it must be committed first.
- **Authorization needed:** the methodology call and the target. **Can proceed:** offline evaluation design.

## 6. TE basis for a league with no TE reception premium

- **Current rule (ADR-015):** non-TEP sources' TE votes are lifted onto the TE++ basis the board anchors on, ×1.21 to ×2.05, as a board-wide constant.
- **Evidence:** the `dynasty_main` scoring card pays no TE reception bonus (`bonus_rec_te 0.0`), and starts two TEs. Starter scarcity and scoring premium are different quantities. The Top 20 audit counts 82 TE rows with 479 converted votes, and the TE edge signal reading 22 SELL to 1 BUY.
- **Alternatives:** (a) keep one shared TE++ board; (b) keep the shared board and add a named league-specific overlay; (c) change the shared basis.
- **Recommendation: (b).** The board is scoring-profile scoped, so a league's TE demand belongs in league-aware overlay work, under its own name. Measure before activating.
- **Risk:** (c) reprices every TE on every surface. (a) leaves a known mismatch for this league.
- **Authorization needed:** the methodology. **Can proceed:** measurement.

## 7. BDVM anchor and signal policy

- **Current rule:** fundamentals are pinned so each strategy's top asset prints 9800, with gamma 1.2. Labels describe a level gap, reworded by #2150.
- **Evidence:** #2163. About 80% of signals read STRONG_SELL. 14-day information coefficient −0.015, whose interval spans zero. Fundamental totals are about 44% of market. Every input is a proxy baseline. No tested challenger passed.
- **Alternatives:** (a) keep serving with the reworded label; (b) preregister a longer evaluation with real projection inputs; (c) change the anchor or gamma.
- **Recommendation: (a) now, (b) once real projection sources exist.** Do not tune thresholds to balance the chart.
- **Authorization needed:** (b) or (c). **Can proceed:** nothing further until real inputs exist.

## 8. Confidence-qualified BUY and SELL output

- **Current rule:** directional labels appear whenever a gap clears its threshold, with confidence shown separately.
- **Evidence:** the directional signal has no measured skill (brief 7). Fundamentals and the gap itself remain useful descriptions.
- **Alternatives:** (a) display as is; (b) qualify with evidence strength; (c) withhold the direction and keep the gap until skill is shown.
- **Recommendation: (c) for directional words.** A signal with no measured skill should not read as advice. Display is frontend-owned, so the backend would publish an explicit `signalEvidence` state for the frontend to consume.
- **Authorization needed:** the policy. **Can proceed:** the additive field, once chosen.

## 9. Source voting restoration

- **Current rule:** `dlfIdp`, `dlfRookieIdp`, DLF Values offense and the Signals IDP families are held. Holds are enforced at deploy by `scripts/verify_owner_held_flags.py`.
- **Evidence:** `docs/sources/REHABILITATION_REVIEW_2026-11-06.md`. Outlier Integrity V2 (#1884, 1,093 commits behind) was the stated precondition and has not passed.
- **Alternatives:** (a) keep holds and extract #1884's identity pieces in small PRs; (b) lift individual holds on separate evidence.
- **Recommendation: (a).** The Hampel filter can drop legitimate votes when the voting population changes, which is why the holds exist.
- **Authorization needed:** any lift. **Can proceed:** read-only four-arm comparison and extraction.

## 10. Protected package-model and fairness parameters

- **Current rule:** `geom_q078_v1` with q = 0.78. Fairness bands `fairness_bands_v2`, with post-launch validation owed under OD-F4.
- **Evidence:** a residual of −0.14 to −0.15 in multi-piece bins over 1,121 trades, with intervals excluding zero (Top 20 audit). The band cut points have not been validated against outcomes.
- **Alternatives:** (a) hold; (b) refit q offline with no market-clearing-equals-fair assumption; (c) change q.
- **Recommendation: (b), then decide.** An accepted trade is not proof of a fair trade, so the fit needs that caveat built in.
- **Authorization needed:** any parameter change. **Can proceed:** offline evaluation.

## 11. Public draft-capital exposure and public Sleeper ids

- **Current rule:** `/api/draft-capital` is unauthenticated by documented design. Public league payloads carry Sleeper owner ids (the raw league and draft ids are already stripped).
- **Evidence:** 7,390 `ownerId` occurrences in `/api/public/league` (Top 20 audit). Draft capital takes about 5.6 s cold.
- **Alternatives:** (a) keep; (b) pseudonymize owner ids; (c) authenticate draft capital; (d) add a rate limit in nginx.
- **Recommendation: (b) and (d), keep draft capital public.** Owner ids are identifying data the page does not need. Rate limiting protects the expensive route.
- **Risk:** (b) needs a frontend consumer check. **Authorization needed:** the exposure choice. **Can proceed:** a consumer census.

## 12. Required GitHub checks and review rules

- **Current rule:** live ruleset `main-protection` has only `deletion` and `non_fast_forward`. Write and admin roles and deploy keys bypass it with `always`. `Validate PR` and `Receipt check` are advisory.
- **Evidence:** a red check cannot stop a merge today. 12 of the last 12 merged PRs were authored and merged by the same account, and GitHub does not allow an author to approve their own PR.
- **Prepared:** `deploy/github/main-protection-ruleset.json` now requires both checks, with the GitHub Actions app and deploy keys as bypass actors so scheduled refreshes keep landing, and admin bypass reduced to `pull_request`. Dependabot and Actions authors are already exempt in the receipt script. Pinned by `tests/deploy/test_main_protection_ruleset.py`.
- **Alternatives:** (a) apply as prepared, 0 required approvals; (b) also require 1 approval, which needs a second GitHub identity or review app; (c) keep it advisory.
- **Recommendation: (a) now.** Consider (b) later if you want review recorded as a GitHub event rather than a PR field.
- **To apply:** `GH_TOKEN=<admin token> bash deploy/github/apply-branch-protection.sh --dry-run`, then without `--dry-run`. Runbook: `docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md` §1.
- **Verify:** the next scheduled refresh lands on `main`, and a PR with a red `Validate PR` refuses a normal merge. **Rollback:** re-run with the previous payload.
- **Risk:** an unlisted direct pusher to `main` is blocked (the pinned test guards this). **Authorization needed:** you must run it; agent credentials cannot.

## 13. Production credential operations

- **Current rule:** the old login literal was removed from source in April 2026 but stays in git history. `server.py` requires the value from the environment.
- **Evidence:** the current production value cannot be checked from outside the box. Rotation has not been recorded.
- **Alternatives:** (a) rotate; (b) rotate and rewrite history.
- **Recommendation: (a).** History rewriting breaks every clone and worktree, and rotation already neutralizes the old value.
- **To apply:** runbook §3. Record only the date, never the value. **Authorization needed:** you must run it on the box.

## 14. Off-machine backup

- **Current rule:** 14 healthy generations per root, all on the production disk. Temporal, analyst and receipt ledgers are optional in the backup script.
- **Evidence:** live `backup_health`, and the Top 20 audit. One disk failure loses irreplaceable history.
- **Alternatives:** (a) a free tier or another host you control, using the existing `OFFBOX_RSYNC_DEST` mirror with client-side encryption; (b) paid storage; (c) accept the risk.
- **Recommendation: (a).** It needs no spending. The mirror carries session secrets, so it must be encrypted first.
- **To apply:** runbook §5. **Authorization needed:** the destination, and any spending. **Can proceed:** making the irreplaceable ledgers required needs box access, so it is prepared, not applied.

## 15. Protected feature activations

- **Held:** `source_freshness_schedule_v2`, `playoff_ros_counted_once`, `trade_multi_team_analysis`, the public Trade Advisor, `dlf_values_rank_hill_vote`, and the Signals IDP vote flags. Some are default-off flags; the vote holds are also enforced at deploy by `scripts/verify_owner_held_flags.py`.
- **Recommendation:** leave all held. Each has its own evidence gate, and none is met today.
- **Authorization needed:** each is separate. Approval of one does not extend to another.

# Residual blocker report — 2026-10-18

**Status: draft. The coordinator refreshes it at campaign close.**

This is Deliverable B of `docs/owner/OWNER_DECISION_CLOSEOUT_2026-10-18.md`. It lists only what stays genuinely
blocked once everything currently actionable is under way. Every item carries three facts:

- **who** can resolve it;
- **what** exactly unblocks it;
- **whether it blocks** a currently authorized production feature.

Decisions and live status: `docs/owner/OWNER_DECISION_REGISTER.md`. Admin procedures:
`docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md`. Draft basis: release train 8 head `3bc9cbfcec` (#1809, approved and
validating, not merged).

## 1. Human-only action

These need credentials, administrator permissions, an official launch or a real-world confirmation.

| item | who | what unblocks it | blocks an authorized production feature? |
|---|---|---|---|
| Re-enable the paused authenticated production verification (`v1-authenticated-verification.yml`, `prod-e2e-smoke.yml`) | owner (repository admin) | `docs/ops/AUTH_VERIFICATION_REENABLE.md`; preconditions met (#1759 merged and deployed 2026-10-16) | **Yes, for proof.** 35 ledger rows wait on an authenticated production check, among them the Trade Calculator, Manager Intelligence and trade discovery |
| Apply the `main` ruleset (D18) | owner (admin token) | runbook §1 | No. It closes a review-bypass risk |
| Deploy-key inventory, then retire unused write keys (D18) | owner (admin) | runbook §2 fingerprint comparison first | No. Retiring the wrong key would break box pushes |
| Rotate `JASON_LOGIN_PASSWORD` (D18) | owner / box operator | runbook §3; record the date only | No |
| `dynasty_main` draft order: does the league-median result count? | owner (league-rule fact) | one yes/no before the 2026 regular season ends (`docs/picks/DRAFT_ORDER_RULE.md`) | Not yet. The 2027 slot forecast stays labelled head-to-head until then |
| VAPID keys | owner (credential) | generate the pair into the box `.env`, restart | No. The in-app inbox works; push needs the keys |
| Optional free keys: BALLDONTLIE, CollegeFootballData (D17) | owner (account) | free account + key, only if the terms allow | No. Game Day shows honest unavailable states for live game-state |
| `OD-01`: IDP Trade Calculator authorization record + credentialed-source posture | owner | one recorded posture per source | No |
| Scope candidates: sixth slot (R40 / R44), `OD-06`, `OD-07` | owner | approve or drop each | No. Candidates only |
| Official rookie auction (D20): rule confirmation, 2027 pool, encrypted off-host recovery copy or risk acceptance, human device rehearsals, launch | owner + league-mates | after the 2027 NFL draft, with checklist A–C complete; runbook §5 | No. Mock-first continues |

## 2. External / time-dependent evidence

These wait on provider updates, future rookie observations or missing historical records.

| item | who | what unblocks it | blocks an authorized production feature? |
|---|---|---|---|
| IDP Show voting board quarantined (vendor chart `U8I37/v4`, 2026-08-19) | vendor | the vendor republishes; freshness weighting lifts automatically | No. The current values are preserved |
| FantasyPros IDP experts stale since 2026-09-04 | vendor | new expert rankings (D5 counts only the upstream clock) | No. The source is reported stale, never zero |
| Unified Manager of the Year trade component: decision-time history | time | complete point-in-time evidence; earliest official season 2027 (D12) | No. The official award is unchanged |
| 2027 rookie class inputs | NFL draft (late April 2027) | the class exists; draft valuation Batch D promotion gates | No |
| Live Game Day game-state source | provider access | a permitted free key (D17) or provider change | No, beyond honest unavailable states |

## 3. Engineering evidence pending

These wait on tests, benchmarks, independent evaluation, replay, deployment or production verification. No owner
action is needed.

| item | who | what unblocks it | blocks an authorized production feature? |
|---|---|---|---|
| `idp-hampel-n3-v1` challenger (D1) | engineering | implement + run on the 105 frozen archives, as preregistered | No. The DLF IDP hold stays |
| IDP-scoped shared cap replay (D2); IDPTC offense vote measurement (D3) | engineering | replay with independent confidence counts; measurement | No |
| DLF Values rank-to-Hill gates (D4) | engineering | D4 gate run + regression + reversible release | No |
| FantasyPros `EXPLICIT_UPSTREAM_TIMESTAMP` + duplicate-identity analysis (D5) | engineering | config change + analysis | No |
| Deep-tail normalization challenger (D6) | engineering | preregistration + holdout run | No |
| Signals IDP box-local dependence + diagnosis (D7) | engineering with box access | an on-box run (`signals-onbox-verification`) | No |
| Package-model evaluation on the production trade archive (D8) | engineering with box access | on-box run against `data/intel` | No. `geom_q078_v1` stays active |
| Playoff-odds AL-5c shadow comparison (D11) | engineering | shadow evaluation with both equations | No. The incumbent stays |
| TCM-K06 unavailable state (D9); TC-B…TC-F (D10) | engineering | TC-B2…TC-F units | Trade Calculator completion |
| D14 chart palette implementation + chart-surface evidence | engineering (Lane 6) | token change through the chart-token owner, desktop/mobile + axe evidence | `/design` chart previews stay gated |
| Release train 8 (#1809) merge + deploy; draft valuation Batch G (#1812) | coordinator | exact-head release gates, deploy, observation | Draft capital Batch E / F and Manager Intelligence F reach production only then |
| Live `packageModel.id` observation (D8) | operator / authenticated verification | the box-local check in the register, or authenticated `/api/data` | No |
| Broken scheduled workflows and unreliable CI tests | engineering | per-incident fixes | No |

## 4. Intentionally deferred

| item | who | what unblocks it | blocks an authorized production feature? |
|---|---|---|---|
| DFS: all implementation and its decisions (ESPN NBA/NHL schedules, DK/FD rules / templates, SportsDataIO slates, contest results, odds) | owner | an explicit owner directive resuming DFS (pause recorded in PR #1810) | No. Deployed DFS is preserved |
| League Tycoon integration, contract dynasty, migration (OD-1…OD-7, evidence capture) | owner | a fresh explicit owner directive | No. Sleeper stays the platform |
| Official 2027 rookie auction activation | owner | readiness + explicit launch authorization (D20) | No |
| Sleeper write gateway (D15); paid inference (D16); paid data services (D17) | owner | a future owner directive with a documented case | No |
| `dynasty_new` draft-order methodology (D13) | owner | an owner request | No |

# Stale and temporary workflow registrations (2026-11-18)

Status: **report only.** Disabling or deleting a workflow registration is an
Actions-settings change reserved for the owner (audit remediation Task 15).
Nothing here was changed in GitHub.

GitHub registers 111 workflows, but `.github/workflows/` on `main` holds 52
files. Of the 59 registrations whose file is not on `main`, 2 are GitHub-managed
dynamic workflows (Dependabot Updates, Dependency Graph) and must be left alone.
The remaining **57** are leftovers from branches or one-shot repair jobs
(13 `_tmp_*`, 2 `_tmp-power-*`, `tmp-v1-59-*`, `*-once`, `materialize-*`,
`patch-*`, `pr-live-*`, `format-*`, `ktc-*` laboratory probes, `ui-*-20260924`,
`zz-enable-prod-verification`). They are all still `active`, so they clutter the
Actions sidebar and could be dispatched from a branch that still carries the file.

Identification method: `gh api repos/<repo>/actions/workflows --paginate`
(path, id, state) diffed against `git ls-tree origin/main .github/workflows/`.

## Owner command

Run once with a token that has `actions: write` (the loop disables, it does not
delete; run history is kept and re-enabling is `.../enable`):

```bash
for id in 359806930 359800585 342733668 342791538 342739346 342765900 342552576 342995528 342659278 342722035 342722990 342550989 342588528 342580854 342576191 324841772 366151815 366184162 353537766 325985839 341409121 324794764 324751206 361043056 361046918 361315460 361312240 353538848 353533360 361041801 324934145 324448239 325073038 324783884 324887419 324854188 324864296 324871595 324842805 324834828 324835500 324856367 356511640 366211281 366212942 366197984 342914717 324784725 366424305 366416825 366444183 343131655 343143359 343138153 324897584 324869719 389153652; do
  gh api -X PUT "repos/jasonleetucker-code/riskittogetthebrisket/actions/workflows/${id}/disable"
done
```

## Registrations to disable (57)

| id | registered path | name |
|---|---|---|
| 359806930 | `.github/workflows/_tmp-power-ruff-format.yml` | Temporary Power Ruff Format |
| 359800585 | `.github/workflows/_tmp-power-week-integrity-repair.yml` | Temporary Power Week Integrity Repair |
| 342733668 | `.github/workflows/_tmp_chatgpt_sharp_score_serialization.yml` | Temporary Sharp score serialization repair |
| 342791538 | `.github/workflows/_tmp_chatgpt_sharp_speed_benchmark.yml` | Temporary Sharp Read-Path Benchmark |
| 342739346 | `.github/workflows/_tmp_chatgpt_v1_27_prod_proof.yml` | Temporary V1-27 production proof |
| 342765900 | `.github/workflows/_tmp_chatgpt_v1_59_postdeploy_proof.yml` | Temporary V1-59 Post-Deploy Production Proof |
| 342552576 | `.github/workflows/_tmp_dispatch_v1_verification.yml` | Temporary V1 verification dispatch |
| 342995528 | `.github/workflows/_tmp_sharp_readpath_speed.yml` | .github/workflows/_tmp_sharp_readpath_speed.yml |
| 342659278 | `.github/workflows/_tmp_sharp_remote_disconnect.yml` | Temporary Sharp Sleeper disconnect repair |
| 342722035 | `.github/workflows/_tmp_v1_16_proof.yml` | Temporary V1-16 roster reconstruction proof |
| 342722990 | `.github/workflows/_tmp_v1_16_reconcile.yml` | Temporary V1-16 reconciliation |
| 342550989 | `.github/workflows/_tmp_v1_76_reconcile.yml` | .github/workflows/_tmp_v1_76_reconcile.yml |
| 342588528 | `.github/workflows/_tmp_v1_84_reconcile.yml` | Temporary V1-84 production reconciliation |
| 342580854 | `.github/workflows/_tmp_v1_89_reconcile.yml` | Temporary V1-89 production reconciliation |
| 342576191 | `.github/workflows/_tmp_v1_prod_harvest.yml` | Temporary V1 production evidence harvest |
| 324841772 | `.github/workflows/autoformat-sharp-681.yml` | Autoformat Sharp 681 |
| 366151815 | `.github/workflows/calculator-ui-audit-once.yml` | Calculator UI audit (temporary, issue 1421) |
| 366184162 | `.github/workflows/calculator-ui-governance-once.yml` | Calculator UI governance (temporary issue 1421) |
| 353537766 | `.github/workflows/dlf-native-value-probe.yml` | DLF Native Value Probe |
| 325985839 | `.github/workflows/faab-freshness-hotfix.yml` | One-time FAAB freshness test hotfix |
| 341409121 | `.github/workflows/format-arbitrage-branch.yml` | Format Arbitrage Branch Once |
| 324794764 | `.github/workflows/format-ffpc-config-test.yml` | Format FFPC production config test |
| 324751206 | `.github/workflows/format-unified-ffpc-branch.yml` | Format unified FFPC branch |
| 361043056 | `.github/workflows/ktc-capture-lab.yml` | KTC isolated browser laboratory |
| 361046918 | `.github/workflows/ktc-evidence-harvest.yml` | KTC diagnostic evidence harvest |
| 361315460 | `.github/workflows/ktc-public-probes.yml` | KTC public availability probes |
| 361312240 | `.github/workflows/ktc-release-dispatch.yml` | KTC frozen release dispatch |
| 353538848 | `.github/workflows/ktc-three-source-seed.yml` | KTC Three-Source Seed |
| 353533360 | `.github/workflows/ktc-value-source-probe.yml` | KTC Value Source Probe |
| 361041801 | `.github/workflows/ktc-verify-bootstrap.yml` | .github/workflows/ktc-verify-bootstrap.yml |
| 324934145 | `.github/workflows/materialize-curated-industry-sharps.yml` | Materialize Curated Industry Sharps |
| 324448239 | `.github/workflows/materialize-ffpc-implementation.yml` | Materialize FFPC implementation |
| 325073038 | `.github/workflows/materialize-sharp-hide-picks.yml` | .github/workflows/materialize-sharp-hide-picks.yml |
| 324783884 | `.github/workflows/materialize-sharp-production.yml` | Materialize Sharp production population fixes |
| 324887419 | `.github/workflows/materialize-sharp-public-api-access.yml` | .github/workflows/materialize-sharp-public-api-access.yml |
| 324854188 | `.github/workflows/patch-ledger-lock-safety.yml` | Patch Ledger Lock Safety |
| 324864296 | `.github/workflows/patch-sharp-explicit-route-registration.yml` | .github/workflows/patch-sharp-explicit-route-registration.yml |
| 324871595 | `.github/workflows/patch-sharp-explicit-startup-registration.yml` | .github/workflows/patch-sharp-explicit-startup-registration.yml |
| 324842805 | `.github/workflows/patch-sharp-records-client-681.yml` | Patch Sharp Records Client 681 |
| 324834828 | `.github/workflows/pr-live-sharp-repair.yml` | PR Live Sharp Repair |
| 324835500 | `.github/workflows/pr-live-sharp-route-probe.yml` | PR Live Sharp Route Probe |
| 324856367 | `.github/workflows/pr-recover-sharp-ledger-production.yml` | PR Recover Sharp Ledger Production |
| 356511640 | `.github/workflows/prepared-serving-permissions.yml` | Prepared serving permissions |
| 366211281 | `.github/workflows/psi-evidence-once.yml` | PSI evidence finalization (temporary issue 1422) |
| 366212942 | `.github/workflows/psi-evidence-origin-once.yml` | PSI evidence origin correction (temporary) |
| 366197984 | `.github/workflows/psi-gallery-once.yml` | PSI gallery implementation and proof (temporary issue 1422) |
| 342914717 | `.github/workflows/tmp-v1-59-ledger-reconcile.yml` | Temporary V1-59 Ledger Reconciliation |
| 324784725 | `.github/workflows/trigger-sharp-materializer.yml` | Trigger Sharp materializer |
| 366424305 | `.github/workflows/ui-gallery-gated-integration-20260924.yml` | Calculator gated gallery integration |
| 366416825 | `.github/workflows/ui-merge-proof-20260924.yml` | Calculator UI exact-tree integration proof |
| 366444183 | `.github/workflows/ui-parity-integration-20260924.yml` | Calculator UI parity integration repair |
| 343131655 | `.github/workflows/v1-27-promote-once.yml` | One-shot V1-27 ledger reconciliation |
| 343143359 | `.github/workflows/v1-56-finalize-once.yml` | One-shot finalize V1-56 verifier repair |
| 343138153 | `.github/workflows/v1-56-verifier-repair-once.yml` | .github/workflows/v1-56-verifier-repair-once.yml |
| 324897584 | `.github/workflows/verify-sharp-422-fix.yml` | Verify Sharp 422 Fix |
| 324869719 | `.github/workflows/verify-sharp-route-hotfix-pr.yml` | Verify Sharp Route Hotfix PR |
| 389153652 | `.github/workflows/zz-enable-prod-verification.yml` | One-shot — enable production verification workflows |

## Scheduled-workflow sweep (last 10 `schedule` runs each)

| workflow | last 10 | disposition |
|---|---|---|
| `audit-rank-form-drift.yml` | 10/10 failure | FIXED here: accepted-state tripwire (`config/ci/rank_form_drift_accepted.json`, `scripts/rank_form_drift_tripwire.py`); drift is standing on issue #898 and is getting worse (offense excess RMSE 53 to 97, IDP 104 to 182 since 2026-08-18), so the owner decision is increasingly due |
| `verify-sharp-production.yml` | push/workflow_run, mostly green but unmeasured | FIXED here: `verdict` job runs only when measured; a failed upstream deploy is a stated SKIP |
| `e2e.yml` | 4/10 failure | other worker owns it |
| `health-check.yml` | 10/10 success | other worker owns it |
| `consensus-edge-revalidate.yml` | 5 old failures then 5 success | recovered, no change |
| `audit-dropped-sources`, `audit-identity-matches`, `intel-refresh`, `prod-e2e-smoke`, `public-league-warmup`, `retention-health`, `scheduled-refresh`, `smoke-test`, `weekly-narratives` | 8-10 success | inspected every `exit 0`: each is a "nothing to close / nothing to commit / health ready" branch; no early-exit on a missing secret. `smoke-test.yml` already documents that it must not skip on an unset `PROD_PUBLIC_URL`. No change |

No further clear vacuous-green case was found among the 13 scheduled workflows
on `main`. Not fixed, listed for follow-up: `e2e.yml` intermittent failures.

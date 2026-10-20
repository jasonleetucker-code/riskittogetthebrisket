# Owner decisions — fairness_bands_v2 (2026-10-20)

**Status:** owner decision record (verbatim). Fairness part only — the same
session's Outlier integrity V2.1 O-1 decision is recorded with that lane, not
here.

- Captured: 2026-10-20 ~19:45 UTC, answered via AskUserQuestion; the choices
  below are the owner's verbatim selections.
- Research behind the questions: the fairness-threshold memo (2026-10-20,
  baseline `origin/main` @ `1511ca1d08`), summarised with its measurements in
  [`docs/trade/FAIRNESS_BANDS_V2_2026-10-20.md`](../trade/FAIRNESS_BANDS_V2_2026-10-20.md).
- Implemented by: `config/trade/fairness_bands.json` (`fairness_bands_v2`,
  status `PRIOR_OWNER_APPROVED_2026-10-20`), `src/valuation_math/fairness_bands.py`
  and its pinned JS mirror `frontend/lib/fairness-bands.js`.

---

## Verbatim record

> # Owner decisions — 2026-10-20 ~19:45 UTC (answered via AskUserQuestion; verbatim choices)
>
> ## Public Trade Advisor fairness threshold (OD-F1, OD-F2, OD-F3/F5)
> Question context (as asked): Overall FAIR still requires every team to be FAIR.
> 1. OD-F1 — Which level counts as FAIR TRADE: **"'Fair' band only (Recommended)"** — matches the private "NO — TOO CLOSE" definition.
> 2. OD-F2 — Gap denominator: **"Package utility (Recommended)"** — removes the deep-package bias with no new constants; 1-for-1 unchanged; shared rule, so it also moves the private meter, Best Offers and the Package Builder (owner was told this in the question).
> 3. OD-F3/OD-F5 — Floor and publication: **"Approve as prior, validate later (Recommended)"** — publish an owner-approved prior (fairness_bands_v2) keeping the 250 floor explicitly; validate after launch against at-the-time market trades (OD-F4 as named post-launch validation).
>
> Still open (not asked): OD-F6 (align or relabel the League Hub trade-history "Fair trade" grade), OD-3 source-permission record, admission sizes (public 2 / 5 s, private 2 / 30 s defaults), F-1 (naming quarantined/stale assets publicly), response floor confirmation, final public launch approval.

---

## What each decision binds

| id | decision | where it lives |
|---|---|---|
| OD-F1 | FAIR TRADE = band `fair` only; a multi-team trade is FAIR only when every team is `fair` | `fairTradeLevels: ["fair"]` in the config; `fairness_bands.counts_as_fair_trade` / `countsAsFairTrade` |
| OD-F2 | Gap ÷ the larger **package utility**, not the larger adjusted side; 1-for-1 unchanged; one shared rule | `basis: "larger_package_utility"`; `fairness_bands.larger_package_utility` / `fairness_base`, JS `fairnessBase` + `trade-logic.js::packageUtilities` |
| OD-F3 | Keep the 250-point floor explicitly, as an owner-approved prior | `absoluteMinimum: 250`, `absoluteMinimumStatus` in the config |
| OD-F5 | Publish `fairness_bands_v2` as an owner-approved prior | `version` / `status` in the config |
| OD-F4 | Named post-launch validation against at-the-time market trades | `postLaunchValidation` (state `PENDING`) in the config |

## Still open (not decided here)

- **OD-F6** — align or relabel the League Hub trade-history "Fair trade" grade
  (`src/public_league/trade_grading.py`, 3.0%, no floor). Not changed by v2;
  the disagreement count is in the evidence doc.
- **OD-3** — source-permission record.
- **Admission sizes** — public 2 / 5 s, private 2 / 30 s defaults.
- **F-1** — naming quarantined / stale assets publicly.
- **Response floor** — confirmation.
- **Final public launch approval.**

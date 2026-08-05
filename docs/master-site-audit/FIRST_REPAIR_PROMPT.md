# First Repair Prompt

Deliverable section 19 of the audit brief: a copy-paste prompt for the single highest-value
repair workstream. **This was not executed during the audit.**

Why this one first: it closes three P0 findings, materially changes a fourth, and moves both
Rankings and the Trade Calculator off *Not trustworthy*. Everything downstream of the board —
trade advice, FAAB, arbitrage, signals — is being computed from a different number than the one
the user reads, so no other repair can be trusted until this is fixed. Estimated size: **S**.

---

## Copy-paste prompt

```
The rankings board the frontend renders is not the board the backend serves, and I need you to
fix the cause without changing what an intentional operator override does.

THE DEFECT

Two lines disagree about what "no override" means:

  frontend/components/useSettings.js:35
      tepMultiplier: 1.15,      // a concrete number, treated as the default

  frontend/lib/dynasty-data.js:919-923
      export function tepMultiplierIsCustomized(tepMultiplier) {
        if (tepMultiplier === null || tepMultiplier === undefined) return false;
        const n = Number(tepMultiplier);
        return Number.isFinite(n);          // ANY finite number reads as "customized"
      }

Only null/undefined mean "auto". The default is 1.15. So `tepCustomized` is true for every user
on every page load, and fetchDynastyData (dynasty-data.js:2073) stamps
`body.tep_multiplier = 1.15` onto every POST /api/rankings/overrides request.

That flips the request onto the override path, which substitutes a flat 1.15 for the backend's
measured ADR-015 TE-basis conversion (src/league_intel/te_premium.convert_te_value — KTC's own
measured uplift, 1.209 at the top of the board rising toward 2.05 down it).

Making it worse: the migration at useSettings.js:182-190 rewrites a stored `tepMultiplier` of
null — the genuine "auto" value — to 1.15 and sets tepDefaultV3Applied so it never reverts. Users
who were on the correct path were migrated off it permanently.

MEASURED CONSEQUENCES (evidence in docs/master-site-audit/evidence/W03/, W07/, W08/, W12/)

  - 627 of 740 ranks and 654 tiers on the rendered board differ from GET /api/data
  - tight ends under-priced by up to 21.2% versus the canonical pipeline
  - the response stamps isCustomized:false while this happens
  - /trade sums the overridden board, so every TE in every package is mispriced
  - the /rankings Edge column labels 32 of 35 top-250 tight ends SELL, and every SELL in the
    top 250 is a tight end — it is measuring basis mismatch, not mispricing

WHAT TO DO

1. Make "auto" representable and make it the default. The settings default must be a value that
   tepMultiplierIsCustomized() reports as NOT customized. Do not change the predicate's meaning
   for a real user-chosen number: an explicit 1.15 chosen by an operator must still post.
   Consider whether the slider needs a separate "auto" state distinct from any numeric value —
   the current model cannot express "auto" and "1.15" as different things, and that is the root
   of the bug.

2. Fix the migration at useSettings.js:182-190. It currently promotes null to 1.15. It must not
   move a user off auto. Decide explicitly what happens to users already migrated — most of them
   never chose 1.15, and leaving them on it preserves the defect for existing installs.

3. Verify the /trade path too. Confirm the calculator sums the same board /api/data serves.

4. Re-check the Edge column after the fix. If TE SELL labels persist at anything like 32/35, the
   column has a second, independent basis problem and needs its own investigation — do not
   assume this fix resolves it, measure it.

CONSTRAINTS

  - Do not add a frontend ranking engine. buildRows stays a pure materializer.
  - Do not change the backend's TE-basis curve. The backend is correct here; the frontend is
    overriding it.
  - An explicit operator override must keep working exactly as it does today.
  - RISKIT_FEATURE_TE_BASIS_CONVERSION=0 must still disable the conversion.

ACCEPTANCE TESTS (all must pass)

  a) With default settings and no user customization, the request body posted to
     POST /api/rankings/overrides contains NO tep_multiplier key.
  b) With default settings, the board rendered on /rankings matches GET /api/data?view=app rank
     for rank across the top 500 — currently 627 of 740 differ.
  c) With an explicit operator value of 1.15, tep_multiplier IS posted and the override path is
     taken (the fix must not make deliberate overrides unreachable).
  d) A fresh install and an install with a stored null both land on auto.
  e) The same tight end shows the same value on /rankings and /trade in one session.
  f) Existing tests stay green: .venv/bin/python -m pytest tests/ -q  and
     npm --prefix frontend test

HOW TO REPRODUCE BEFORE AND AFTER

  Boot the stack the way the audit did — see docs/master-site-audit/EVIDENCE_LOG.md, which has
  the exact commands, the scrape-suppression launcher, and the Playwright request-interception
  requirement (a browser pointed straight at :3000 does not reproduce production and will give
  you false results).

Report what you changed, what the rank-agreement number went from and to, and anything you found
that this description got wrong.
```

---

## After this one

The next repair is **size XS** and closes three more P0s: in the ROS snapshot loader,
`sorted(snapshot.seasons, key=luck._season_sort_key)` passes season objects to a function typed
for strings, so every key compares equal, the sort is a no-op, and the simulator runs on the
oldest loaded season (2024) instead of the newest. Fix the key, then fix the separate coercion
that turns "absent from the sim" into 0.0 playoff odds — which is what tells the best roster in
the league to sell. Findings W17-F001, W17-F002, W20-F002.

Full ordering in `REPAIR_ROADMAP.md`.

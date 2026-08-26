# V1-27 authenticated production verification — 2026-08-26

This record closes only evidence that was actually observed. It does not change methodology, scope, auth, or any runtime path.

## Source

- GitHub Actions run: `32919648642`
- Deployed origin exercised by the run: `https://risk-it-to-get-the-brisket-web.onrender.com`
- Auth: ephemeral `guest_pass` session minted on-box, logged into production, then revoked by the workflow.
- Verification head: `6e07be744bd73f2f5fdca70e213b4a7ba39667c0`.

The aggregate workflow verdict was red because other V1 rows failed their own assertions. V1-27's row-specific assertions passed and are recorded independently below; no aggregate red is re-labelled green.

## C2-U1 §10 evidence

### Item 2 — deployed browser consumers

`tests/e2e/specs/prod-auth/v1-27-lineup-render.spec.js` passed both desktop assertions against production:

1. `/terminal` rendered the server-stamped `optimalLineup` starter/bench split for a real team, including the truth-ladder disclosure and unpriced third-state behavior.
2. `/rosters` “Starters only” scope was driven by the stamped lineup with the honest unavailable state retained.

Result: **PASS, EVIDENCE-L3**.

### Item 3 — deployed trade simulation

`scripts/verify_v1_authenticated.py` selected a real tail-bench-for-tail-bench swap and observed:

`starterDelta={'QB': 0, 'RB': 0, 'WR': 0, 'TE': 0, 'DL': 0, 'LB': 0, 'DB': 0, 'K': 0}`

Payload used league `dynasty_main`, team `468418790212759552`, player out `Trevin Wallace`, player in `Tyrone Tracy`.

Result: **PASS, EVIDENCE-L3**.

### Previously established items retained

The canonical C2-U1 record already establishes:

- item 1: 12/12 teams carry `optimalLineup.available=true` with `slotSource=sleeper_roster_positions` on the real board;
- item 3a: lineups remain available with the Sleeper block populated/reachable;
- item 5: 660 eligibility records, 43 multi-position players, 31 starters, with four observed hybrid-slot starts;
- item 4: pre-merge on-box golden-board inertness plus a healthy post-deploy scrape. The owner decision recorded 2026-08-25 in `docs/VERSION_1_COMPLETION_CONTRACT.md` authorizes this substitute where the missing pre-deploy production snapshot is permanently irrecoverable. This record does not invent a lost snapshot.

## Truth-preserving conclusion

The production-session blocker named by V1-27 is no longer present for checklist items 2 and 3. Combining the authenticated L3 observations above with the already-recorded real-board evidence and the owner-authorized item-4 substitute satisfies the stated V1-27 closure route without changing the canonical lineup owner or weakening any invariant.

This evidence record alone does not silently promote the completion ledger; the ledger update must remain an explicit reviewed integration change.
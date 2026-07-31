# Sharp Score — methodology

**Version:** `sharp-v2`  
**Config:** `config/sharp/scoring_v2.json`  
**Code:** `src/sharp/score.py`

Sharp Score v2 is platform-neutral. The addition of FFPC does **not** change any weight, gate, percentile, confidence threshold, or qualification rule. Platform adapters may only normalize evidence into the existing `ManagerRecord`; they may not implement a source-specific score.

## Evidence boundary

A league-season may certify a manager only when all required evidence is known:

- stable, verified global manager identity
- confirmed dynasty league that meets the configured age requirement
- completed season
- wins, losses, ties, and completed games
- final rank and team count
- playoff and championship results
- observable recent activity when the platform evidence is expected to satisfy the existing activity/recency gates

Unknown values remain unknown and make the season row ineligible for automated scoring. They are never converted to zero.

Sleeper evidence is collected through the existing discovery and records crawls. FFPC evidence can enter the same automated population only when public/configured records meet the same standard. League-scoped FFPC team identities, name-only identities, incomplete standings, and unverified historical chains remain inspectable but do not become automated qualifiers.

Curated FFPC high-stakes managers use a separate qualification method, `curated_high_stakes`. They are never represented as having passed `sharp-v2`, and their observations contribute only when explicitly enabled in `config/sharp/ffpc_sources.json`.

## Three gates

| Gate | Question | Evidence admitted |
|---|---|---|
| Discovery | Can this source introduce a manager? | Broad source-specific population |
| Signal | May a transaction inform dynasty buy/sell activity? | Confirmed dynasty/keeper trade movements; waivers remain separate |
| Sharp | May a season certify manager skill? | Confirmed dynasty only, old enough, complete, and fully evidenced |

Discovery eligibility never implies signal eligibility, and signal eligibility never implies Sharp qualification.

## Hard eligibility gates

The values remain controlled by `scoring_v2.json`:

- minimum completed seasons
- minimum qualifying dynasty leagues
- minimum league age
- minimum completed games
- minimum win percentage
- maximum abandoned-roster rate
- recent-activity requirement

Failing any gate produces `evaluable=false` with reasons rather than a low score.

## Components and unchanged formula

```text
score = performance weight × performance
      + roster-quality weight × roster quality
      + consistency weight × multi-league consistency
      + longevity weight × longevity
      + activity weight × activity
      + bounded championship bonus
      - explicit uncertainty penalty
```

The exact current numbers live only in `config/sharp/scoring_v2.json`; this document intentionally does not create a second source of truth.

- **Performance:** win percentage, playoff rate, shrunk championship rate, finish, and points-for evidence.
- **Roster quality:** value relative to each league's own average plus age/depth/pick adjustments where available.
- **Multi-league consistency:** share of qualifying leagues above median with variance control.
- **Longevity:** saturating credit for sustained history.
- **Activity:** capped participation evidence, not raw churn.
- **Championship preference:** bounded bonus, not a hard title gate.
- **Uncertainty:** explicit penalty and separate confidence output.

## Qualification

Managers must clear both the configured score-percentile bar and confidence bar. Score and confidence remain separate. Population percentiles are calculated among evaluable records, while coverage also reports qualified share of the full observable population.

## Platform-scoped identity

`ManagerRecord.user_id` is a platform-scoped manager key such as `sleeper:123` or `ffpc:site-user-456`. Matching display names never merge records. An explicit `canonical_manager_id` may reconcile unique-manager breadth across sources, but automated qualification remains grounded in verified evidence rows.

See `docs/intel/FFPC_UNIFIED_SHARP.md` for collection, canonical assets, curated qualification, source reconciliation, and operational details.

# W1-10 — Week 1 matchup-data audit, 2026-09-05

**Row:** `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` W1-10 — *"All six Week 1
league matchups are present with correct managers/teams/schedule and current,
non-fabricated data inputs."*

**Method:** production `GET /api/public/league/matchupPreview` compared field by
field against Sleeper as ground truth (league `1312006700437352448`, plus the
2025 `1180092661344120832` and 2024 `1090320428817592320` links of the same
chain). Read-only; no fixtures, no repo snapshots.

**Verdict at audit time:** everything the row asks for is present and correct
**except one missing-is-never-zero defect**, found and repaired here. W1-10
cannot move to `VERIFIED` until that repair is deployed and re-checked on
production — the code fix is not the acceptance evidence.

---

## 1. Presence, schedule and identity — all correct

`data.currentSeason 2026`, `currentWeek 1`, `mode "preview"`, `isPlayoff false`,
six matchups, 12 distinct `ownerId`s, `generatedAt 2026-09-05T12:54:32+00:00`.

Every pairing matches Sleeper's `/matchups/1` exactly:

| matchupId | roster pair (prod) | roster pair (Sleeper) | ownerIds |
|---|---|---|---|
| 1 | 5, 7 | 5, 7 | match |
| 2 | 3, 12 | 3, 12 | match |
| 3 | 8, 11 | 8, 11 | match |
| 4 | 1, 4 | 1, 4 | match |
| 5 | 2, 10 | 2, 10 | match |
| 6 | 6, 9 | 6, 9 | match |

Sleeper reports 12 week-1 rows, six `matchup_id`s of two rosters each, no null
`matchup_id`, and **no nonzero points** — the week is genuinely unplayed and the
league is `status: in_season`, `state/nfl` `season 2026 week 1 regular`.

**Team names are a documented fallback ladder, not fabrication.** Five of the
twelve managers have no `metadata.team_name` set on Sleeper (it is `None` or
`""`). `identity.py` resolves `metadata.team_name → user.display_name →
"Team {rosterId}"`, so production shows e.g. `CollinFoz` and `ughb`. Every value
served is Sleeper-derived; nothing is invented.

**Unplayed points are `null`, not `0`** on all twelve sides.

## 2. The H2H block is correct, including a non-obvious aggregation

Spot-checked matchup 4 (Jason vs Collin) against every meeting in the chain.

A naive per-week scan of Sleeper finds **five** rows: 2024 wk8, 2024 wk16,
2024 wk17, 2025 wk3, 2025 wk12. Production reports **four** meetings with
`playoffMeetings: 1`. Production is right and the naive count is wrong: the 2024
playoff was a **two-week aggregate**, and production sums it into one meeting —

```
317.95 + 274.07 = 592.02   (Jason)
295.14 + 320.71 = 615.85   (Collin)
```

which is exactly what the `last5` entry for `2024 wk 16, isPlayoff: true`
carries. Recounted correctly the series is 2-2, `avgMargin`
`(19.21 + 23.83 + 56.02 + 108.0) / 4 = 51.77`, `biggestMargin 108.0` — all three
match production, as does the narrative string.

## 3. Defect found — an empty H2H series was rendered as a dead heat

Two of the six matchups (2 and 3) are **first-ever meetings**: Blaine and
jstuedle joined for 2026 and their alias lists carry 2026 only. Production
served:

```json
{"totalMeetings": 0, "avgMargin": 0.0, "biggestMargin": 0.0,
 "narrative": "First ever meeting between Blaine and Ty."}
```

An average and a maximum over an empty series are **undefined, not zero**, and
the reading `avgMargin: 0.0` invites is the opposite of the truth: *these two
always play to a dead heat.* The sibling `_form_summary` already gets this right
— it publishes `avgPoints: null` for a manager with no games — so this was an
inconsistency inside one module, not a missing convention.

**It is not cosmetic.** `matchup_narrative._build_brief` copies the block into
the brief and `json.dumps`es it verbatim into the article-generation prompt, so
the generator was being handed a fabricated dead-heat series for exactly the two
matchups with no history. That is a W1-11 quality failure manufactured upstream.

### Repair

- `matchup_preview._h2h_summary` returns `None` for `avgMargin`,
  `biggestMargin` and `biggestMarginWinner` when there are no meetings.
- `matchup_narrative._build_brief` drops its `.get(key, 0.0)` defaults, which
  would otherwise re-coerce the `None` straight back to `0.0`.

**Counts deliberately stay `0`:** `sideAWins`, `sideBWins`, `ties`,
`playoffMeetings` are tallies of things that happened zero times, and
`sideAPointsTotal` / `sideBPointsTotal` are sums over an empty set. Those are
facts. Only the average and the extremum are undefined, and only they changed.

A **tie** stays distinct from an empty series and is pinned by its own test: a
tie *has* a margin (zero) and no winner; an empty series has neither.

Pinned by `tests/public_league/test_matchup_preview.py`
(`EmptySeriesIsMissingNotZeroTests`, 4 tests) and
`tests/public_league/test_matchup_narrative.py`
(`BriefDoesNotReintroduceZeroMarginTests`, 2 tests — one behavioural, one
structural, because the coercion is one word long and reads like ordinary
defensive code in a diff).

`config/coercion_baseline.json` is **not** touched: neither idiom
(`... if total else 0.0`, `.get(key, 0.0)`) was in the baseline, so nothing is
burned down and the file's known merge hazard is avoided.

## 4. Row status

`W1-10` stays **NOT STARTED → IN PROGRESS**, not `VERIFIED`. The data audit
passes on every clause except the one defect, and the repair is code, not
production evidence. It moves to `VERIFIED` when this is merged, deployed, and
`GET /api/public/league/matchupPreview` serves `avgMargin: null` for matchups 2
and 3 on production.

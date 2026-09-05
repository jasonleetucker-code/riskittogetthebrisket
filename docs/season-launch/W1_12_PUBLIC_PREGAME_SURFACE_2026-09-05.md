# W1-12 — the current week's pregame content was reachable from no public surface

**Row:** `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` W1-12 — *"Week 1 pregame
surfaces pass mobile/navigation/link/degraded-state production verification."*

**Found while auditing W1-10** (`W1_10_WEEK1_MATCHUP_AUDIT_2026-09-05.md`), which
proved the Week 1 pregame *data* on production is present and correct. This
document is about where that data goes, which turned out to be nowhere.

---

## 1. The gap

On 2026-09-05 — Week 1 of the season, `state/nfl` `season 2026 week 1 regular`,
kickoff Thursday 2026-09-10 — production served:

```
GET /api/public/league/matchupPreview
  currentSeason 2026 · currentWeek 1 · mode "preview" · 6 matchups
  every pairing, ownerId and rosterId matching Sleeper exactly
```

and the public site rendered **none of it**:

- `/league` (Home) shows a single-matchup teaser card with one H2H narrative
  line and a "Full H2H preview →" CTA.
- That CTA calls `onNavigate("matchupPreview")`, which `tabs.js` aliases to the
  `previews` tab.
- The `previews` tab is `ArticlesSection`, which renders **AI-written articles**
  and falls back to the most recent `(season, week)` group that has any. There
  are **zero 2026 Week 1 articles** — `weekly-narratives.yml` skips generation
  after its key check because `ANTHROPIC_API_KEY` is not configured (the named
  W1-11 blocker) — so the tab landed on **2025 Week 17**.

So the six Week 1 head-to-head previews were computed, served, correct, and
unreachable. The CTA promising a "full H2H preview" led to last season's
championship articles.

**This was a deliberate design that stopped holding.** `tabs.js` records the
reasoning for retiring the old structured "This Week" tab: *"the articles
surface the same H2H + form data inline (the brief is built from it), so the
structured-data tabs are redundant once articles are wired in."* That is true
whenever an article exists for the current week. It is exactly false when none
does, and nothing covered that case.

A second, smaller problem in the same place: the heading did name the older
slate's season and week (`"Week 17 previews · 2025"`), but the subhead read
*"Wednesday-morning previews. Tap a card for the full article."* in the present
tense, with nothing saying the current week has none. Labelled, but not flagged.

## 2. The repair

`frontend/app/league/sections/matchup-previews.jsx` (new) is the `previews` tab.
It composes, in reading order:

1. the **structured head-to-head block** for the current week, read verbatim
   from the canonical `matchupPreview` contract section;
2. `ArticlesSection` below it, unchanged in substance.

Four constraints, all load-bearing:

- **It is a fallback path for a missing article, not a second preview owner.**
  It renders only while the contract reports `mode === "preview"` — the week is
  genuinely unscored. Once the week scores, the recap surfaces own it and the
  block disappears. Pinned by a test.
- **It recomputes nothing.** Every number is read from the section; the
  component is a materializer, the same relationship the rest of `/league` has
  with the contract. It does not resolve the clock either — `currentSeason` /
  `currentWeek` come from the contract, because a second answer to "what week is
  it" is the duplicate owner this repo spends most of its rules avoiding.
- **Missing is never zero, in the renderer too.** A first-ever meeting renders
  "First meeting" and no margin; a manager with no prior games renders "No prior
  games", not "0-0"; a null `avgPoints` prints nothing rather than `0.0`. The
  `totalMeetings === 0` guard runs *before* any margin is read, so the tab is
  correct even against a backend that has not yet taken the companion
  `_h2h_summary` fix.
- **Degrade, never fail.** A 503 or a network error on the optional structured
  block leaves the article slate rendering; the failure is not cached, so a
  transient error does not suppress the block for the rest of the session.

`ArticlesSection` gains optional `currentSeason` / `currentWeek` props. When
supplied and the newest slate is older, the heading becomes *"Most recent
previews · 2025 Week 17"* and the subhead becomes *"No previews written yet for
2026 Week 1 — these are the most recent on file."* **An unknown clock is
reported as neither a match nor a mismatch** — both props must be present for
the check to fire — so the Recaps tab and any other caller are unchanged.

## 3. What this does NOT do

- It does not generate any article. `ANTHROPIC_API_KEY` remains the W1-11
  blocker and only the owner can clear it.
- It does not touch the private/public boundary: everything rendered is
  factual, retrospective league history already published by the public
  contract. No values, edges, targets, forecasts or projections.
- It does not change any contract data, and it does not move W1-10.

## 4. Verification

- `frontend/__tests__/components/league-previews-section.test.jsx` — 8 tests:
  the structured block renders for an unscored week; a first-ever meeting shows
  no margin (`avg margin 0` must appear nowhere); "No prior games" rather than
  `0-0`; the block is withheld once the week is scored; the tab still renders
  when the preview section is unavailable; and three on the article-slate
  labelling including the unknown-clock case.
- `npx vitest run` — **2416 passed / 165 files**.
- `npm run build` — clean; `/league/page` **38.0 KB against a 50 KB budget**,
  all 14 budgeted pages under. The section is code-split, so its cost lands only
  when the tab is opened.

## 5. Row status

`W1-12` stays **NOT STARTED**. This closes the reason it could not pass — there
is now a surface for the current week's pregame content — but the row's own
acceptance is *production* verification of mobile, navigation, links and
degraded states, and that requires this to be deployed and then checked on
production. Implementation is not verification.

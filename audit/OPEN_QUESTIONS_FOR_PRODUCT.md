# Open Questions for Product

These came out of the 2026-04-28 / 2026-04-29 full-site audit and require
product-side judgment, not engineering. Each question lists what the
audit found, what's at stake, and a recommended default if you don't want
to think about it.

---

## 1. KTC top-150 hard gate on trade suggestions

**Where:** `src/trade/finder.py` and `src/trade/suggestions.py` filter their
output to offense players ranked ≤150 in KTC. There is no config knob.

**Audit finding:** the gate is intentional per existing comments — keeps
suggestions grounded in roster-relevant assets — but it breaks down for
deeper league formats. A 14-team 2QB or deep-IDP keeper league has rosters
with 200+ rostered offense players; the top-150 filter silently drops
half their assets from suggestions.

**At stake:** users in deeper leagues see suggestions that look thin or
miss obvious moves, with no UI hint about why.

**Options:**
- **A.** Leave as-is. Document the limitation in /trade UI ("suggestions
  drawn from KTC top 150").
- **B.** Make the cap a configurable setting (default 150, max 300+).
- **C.** Compute the cap dynamically from league depth (rosterSize ×
  teamCount × ~0.7).

**Recommended default:** **B**, because it's a 5-line change and gives
power users an escape hatch. Default 150 keeps the existing experience
for everyone else.

---

## 2. ROS engine rollout scope

**Where:** five feature flags in `frontend/components/useSettings.js`:
`rosEnabled`, `useRosPowerRankings`, `useRosPlayoffOdds`,
`showRosTradePanel`, `showRosTags`. The ROS pipeline (six adapters,
per-team strength, playoff/championship sims, buyer/seller direction,
player tags) is fully built but gated.

**Audit finding:** the engine is shipped end-to-end. Code paths exist for
every surface. The flags are off-by-default for all but `rosEnabled` and
the trade panel/tags. It's unclear whether the gates are temporary
(awaiting validation) or permanent (opt-in features).

**At stake:** five features that work but aren't visible to the user
unless they go to /settings and flip toggles.

**Options:**
- **A.** Flip every ROS flag to default-on. ROS becomes the standard
  experience; users opt out.
- **B.** Keep flags off, advertise the toggles in the /settings page
  with a "try the rest-of-season engine" callout.
- **C.** Run an A/B comparison (current vs ROS-driven) on power rankings
  + playoff odds for a few weeks before flipping defaults.

**Recommended default:** **A** — the engine is well-tested (82 tests,
1,955 backend tests overall, deterministic math). Letting it default-on
is the natural rollout step.

---

## 3. Multi-league completion plan

**Where:** registry has two leagues (`dynasty_main`, `dynasty_new`). The
`useDynastyData` hook threads `?leagueKey=` correctly, the trade endpoints
accept it, the ROS scrape iterates active leagues. Per-league output paths
(team-strength, sim caches) are wired.

**Audit finding:** the plumbing works. The remaining gaps are
*UX-shaped*: per-league signals visibility, watchlist relevance, per-league
user prefs (active team, preset name), per-league push notifications. The
existing single-league experience just happens to also work for the
default league.

**At stake:** users with two leagues currently can't tell at-a-glance
which league a signal/watchlist entry refers to.

**Options:**
- **A.** Stop the migration here. Multi-league works for power users who
  understand they're switching contexts.
- **B.** Ship a per-league badge on every roster/signal/watchlist row.
  Small lift (~1 day), big clarity win.
- **C.** Full multi-league IA: sidebar shows each league's terminal
  side-by-side, switch becomes a tab not a setting.

**Recommended default:** **B**. The minimum-viable visual
disambiguation. Defer C until you actually have 3+ leagues.

---

## 4. Hill curve refit cadence

**Where:** `.github/workflows/refit-hill-curves.yml` is `workflow_dispatch`
only. No cron. The script (`scripts/auto_refit_hill_curves.py`) detects
drift >50 RMSE points and commits if found, but nothing is currently
running it.

**Audit finding:** drift watcher is dormant. Hill curves fit Aug–Sept
2025 are still serving production. Spec says "monthly refit"; reality is
"never since dispatch was added".

**At stake:** if curve drift accumulates, blended values drift away from
true market positions silently. Hard to detect without a manual run.

**Options:**
- **A.** Add a monthly cron (e.g. `0 9 1 * *`).
- **B.** Add a weekly cron in dry-run mode (no commit, just alert if
  drift detected).
- **C.** Leave manual; trust the audit-dropped-sources weekly cron to
  catch egregious drift via the Hampel filter signal.

**Recommended default:** **B**. Weekly dry-run alerting gives early
warning without surprise commits. Promote to commit-mode after one
quiet month.

---

## 5. JASON_LOGIN_PASSWORD rotation cadence

**Where:** `.env` on the production VPS (after audit M1 migrated it
from a source-code default).

**Audit finding:** password is now correctly out of source. No automated
rotation; no audit log of when it was last changed (last change pre-dates
this audit run).

**At stake:** private-app gate is the only thing between random visitors
and the (admittedly read-only) rankings UI. A leaked password requires
manual rotation.

**Options:**
- **A.** No rotation policy. The user is the only intended user; if you
  suspect leakage, rotate manually.
- **B.** Quarterly rotation reminder (calendar event, no automation).
- **C.** OAuth migration (Discord, Google, GitHub). Eliminates password
  rotation entirely.

**Recommended default:** **A** for now. Revisit if traffic patterns
suggest someone other than you is hitting the gate.

---

## How to use this document

Pick a question. Tell me which option (A / B / C). I'll implement it as a
dedicated PR — not a follow-up audit pass.

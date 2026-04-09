# Where Things Actually Stand

_Updated: 2026-03-22 (post Phase B-F execution)_

This is the honest status of the platform, written for anyone who needs to understand what works, what doesn't, and what's next — without reading 10 technical docs.

---

## What runs in production right now

The live site at `riskittogetthebrisket.org` is powered by the **legacy stack**:

1. **Dynasty Scraper** fetches values from up to 11 external sites (KTC, FantasyCalc, DynastyDaddy, etc.) every 2 hours using a headless browser.
2. **server.py** takes those values, blends them into a composite score per player, applies league scoring adjustments, and serves the result as JSON.
3. **Static frontend** (vanilla JS) renders the trade calculator, rankings, roster dashboards, and draft capital pages.

**Nothing about the new system has changed what users see.** The new work described below runs alongside production but does not touch live values.

---

## What the canonical pipeline can now do

The "canonical pipeline" (`src/`) is the replacement value engine. Here's what's real:

**Source integration is fully configured:**
- 5 sources active and producing values (4 DLF + FantasyCalc)
- 11 additional sources have config entries and will auto-activate when the scraper exports their CSVs
- **No new code needed** to add KTC, DynastyDaddy, or any other scraper source — just need the CSV to appear
- Missing CSVs are handled gracefully (warnings, not errors)

**Pipeline runs end-to-end:**
- Source pull → identity resolution → canonical build → snapshot file
- 747 assets across 4 universes, 264 with multi-source blending
- Shadow comparison with legacy values works

**Comparison batch system exists:**
- `scripts/run_comparison_batch.py` produces machine-readable JSON + founder-readable Markdown
- First batch shows: 62% top-50 overlap, avg delta 2903, 13% tier agreement
- This divergence is expected with only 2 of 11+ sources

**Promotion is now rule-based:**
- `config/promotion/promotion_thresholds.json` defines concrete requirements for each mode
- `scripts/check_promotion_readiness.py` evaluates current state against thresholds
- Runtime endpoint at `GET /api/scaffold/promotion` returns live readiness status
- Shadow mode is ready. Internal-primary and public-primary are not.

**Weighting is settled:**
- One weighting implementation, one config file, no competing branches
- All weights are 1.0 (founder needs to tune)

---

## What is still disconnected or incomplete

**The canonical pipeline does not feed production values.** Even though it produces valid snapshots, `server.py` does not serve those values to users. Closing this gap requires:

1. **More sources flowing** — KTC and DynastyDaddy CSVs need to appear from the scraper
2. **Source weight tuning** — founder decision on relative source weights
3. **Top-50 overlap above 70%** — currently 62%, needs more sources
4. **League context engine** — `src/league/` is a placeholder. Scarcity and replacement math have been intentionally removed from the system (LAM and positional scarcity fully deleted).

**Promotion readiness checks show 6 failures for internal-primary.** The specific blockers are measured and documented in `docs/status/promotion-readiness.md`.

**The Next.js frontend is a partial migration.** Trade calculator and rankings work. League Edge, Roster, Trade History, Draft Capital, and Settings are not migrated.

---

## What comes next (in priority order)

**1. Get more scraper CSVs flowing** (no code changes needed)
- Run the legacy scraper with KTC, DynastyDaddy, IDPTradeCalc succeeding
- Their config entries and weight entries already exist
- This is the single highest-leverage action

**2. Tune source weights** (founder decision)
- Currently all 1.0 — needs relative weighting (e.g., KTC > FantasyPros?)
- Required for internal-primary promotion

**3. ~~Build the league context engine~~** (`src/league/`)
- Scarcity multipliers and replacement baselines have been removed from the system
- LAM (League Adjustment Multiplier) and positional scarcity fully deleted
- Pick curves and TEP remain as the active league-level adjustments
- `src/league/` is now a gutted placeholder (`scarcity.py`, `replacement.py`, `settings.py` deleted)

---

## For technical details

| Topic | Document |
|-------|----------|
| Full codebase walkthrough | `HANDOFF.md` |
| Source-by-source integration status | `docs/status/source-integration-tracker.md` |
| Promotion readiness and thresholds | `docs/status/promotion-readiness.md` |
| What the blueprint says vs what exists | `docs/status/master-implementation-audit.md` |
| Comparison batch results | `data/comparison/comparison_report_*.md` |
| Which planning docs to trust | `docs/status/blueprint-source-of-truth.md` |

---

_This document reflects the actual state of the codebase, not the intended state. All numbers come from real pipeline runs and comparison batches, not estimates._

# Where Things Actually Stand

_Updated: 2026-03-22_

This is the honest status of the platform, written for anyone who needs to understand what works, what doesn't, and what's next — without reading 10 technical docs.

---

## What runs in production right now

The live site at `riskittogetthebrisket.org` is powered by the **legacy stack**:

1. **Dynasty Scraper** fetches values from up to 11 external sites (KTC, FantasyCalc, DynastyDaddy, etc.) every 2 hours using a headless browser.
2. **server.py** takes those values, blends them into a composite score per player, applies league scoring adjustments, and serves the result as JSON.
3. **Static frontend** (vanilla JS) renders the trade calculator, rankings, roster dashboards, and draft capital pages.

This system works. It has been running in production for months. The scraper is fragile (some sites fail regularly, some require manual session tokens), but the partial-scrape safety net keeps the site running even when individual sites go down.

**Nothing about the new system has changed what users see.** The new work described below runs alongside production but does not touch live values.

---

## What "canonical" and "shadow" mean

We're building a **replacement value engine** in `src/` that's designed to be cleaner, more testable, and multi-source from the ground up. It's called the "canonical pipeline."

Here's the key distinction:

- **Legacy path** (live): Dynasty Scraper → server.py → your browser. This is what you see today.
- **Canonical path** (experimental): DLF CSVs + FantasyCalc → canonical pipeline → snapshot file on disk. Nobody sees this unless they look for it.

When `CANONICAL_DATA_MODE` is set to `shadow` (it defaults to `off`), the server loads the canonical snapshot and attaches comparison data to the API response. The comparison data shows how canonical values differ from legacy values — but **it does not replace them**. Legacy values remain authoritative. Shadow mode is a diagnostic tool, not a feature toggle.

There is also a `primary` mode defined in config, but it is **not implemented** and should not be used. Switching to canonical-sourced production values requires work that hasn't been done yet.

---

## What parts of the new system are real

These are not aspirational — they exist, run, produce output, and have tests:

**Canonical value pipeline** (`src/canonical/`)
- Takes player rankings/values from multiple sources
- Normalizes them to a common 0–9999 scale
- Blends them with configurable weights
- Produces a snapshot file with per-player values
- Currently blends **2 sources** (DLF + FantasyCalc) for 264 offensive players
- 747 total assets across 4 universes (offense vet, offense rookie, IDP vet, IDP rookie)

**Source adapters** (`src/adapters/`)
- DLF CSV adapter: reads the manually-maintained DLF ranking CSVs. Functional, tested.
- Scraper Bridge adapter: reads the `name,value` CSVs that the legacy scraper already exports. This is how FantasyCalc gets into the pipeline. The same adapter can ingest KTC, DynastyDaddy, and every other scraper source — each just needs a config line, not new code.

**Identity resolution** (`src/identity/`)
- Maps "Josh Allen" from DLF and "Josh Allen" from FantasyCalc to the same player
- 4-tier confidence ladder (1.00 → 0.98 → 0.93 → 0.85 depending on how much metadata matches)
- Handles suffix stripping, accent folding, apostrophe normalization

**Shadow comparison** (`server.py`)
- When enabled, computes per-player deltas between canonical and legacy values
- Reports top risers, top fallers, rank correlation, and distribution analysis
- Available via `GET /api/scaffold/shadow` for inspection
- Logs structured comparison on every scrape cycle

**Scoring module** (`src/scoring/`)
- Computes league-specific adjustments (Superflex QB premium, TEP TE boost, etc.)
- Already integrated into the legacy scraper's `compute_empirical_lam()` flow
- 11 files, ~1,000 lines, tested

**Test suite**
- 250 Python tests (adapters, transforms, identity, scoring, API contract, integration)
- 72 JavaScript tests (trade calculator logic, data normalization)
- No tests existed for the canonical pipeline before this work cycle

---

## What is still disconnected or incomplete

**The canonical pipeline does not feed production values.** Even though it produces a valid snapshot, `server.py` does not serve those values to users. The live site still runs entirely on the legacy scraper. Closing this gap requires:

1. A league context engine (`src/league/`) that applies scarcity, replacement baselines, and pick curves to canonical values. This module is **empty** — not partially built, just empty. It's the biggest missing piece.
2. A cutover path in `server.py` that can serve canonical values as primary instead of legacy values. The shadow wiring exists, but primary mode does not.
3. Validation that canonical values are at least as good as legacy values for the use cases that matter (trade evaluation, rankings).

**Multi-source blending is limited.** Only 2 of the 11+ legacy scraper sources flow through the canonical pipeline (DLF + FantasyCalc). The adapter for the remaining sources is built and ready — the blocker is that the last scraper run didn't export CSVs for KTC, DynastyDaddy, etc. When those CSVs appear, adding each source is a config-file change.

**IDP has zero multi-source blending.** The IDP universe (185 players) comes only from DLF. IDPTradeCalc is the most likely second source but its scraper export isn't available yet.

**Source weights are all equal.** Every source is weighted 1.0 in the blend. This is a placeholder. The founder needs to decide relative weights (e.g., should KTC count more than FantasyPros?) before canonical values can be trusted for production.

**The Next.js frontend is a partial migration.** Trade calculator and rankings work. League Edge, Roster Dashboard, Trade History, Draft Capital, and Settings are not migrated. The Next.js login page is demo-only — real auth uses the Static frontend's landing page.

---

## What comes next (in order)

**1. More sources into the canonical pipeline** (config-only, no new code)
- KTC and DynastyDaddy are next, as soon as the legacy scraper exports their CSVs
- IDPTradeCalc for IDP blending
- Each additional source is a 5-line JSON config entry

**2. Source weight decisions** (founder input needed)
- Should KTC and FantasyCalc have equal weight?
- Should DLF (rank-based, expert-curated) be weighted differently than FantasyCalc (crowd-sourced values)?
- These decisions can't be made by code — they require the founder's judgment about which sources are most trustworthy

**3. League context engine** (biggest build remaining)
- Scarcity multipliers (how much more valuable is a top-5 QB vs a top-20 RB?)
- Replacement baselines (what's the value of "a replacement-level TE"?)
- Pick curves and time discounts (how much is a 2027 1st worth vs a 2026 1st?)
- This is the critical path item. Without it, canonical values are raw market blends with no league-specific intelligence.

**4. Canonical → production wiring** (requires league engine)
- Define exit criteria: what does "canonical values are good enough" mean?
- Build A/B comparison tooling (partially done via shadow mode)
- Switch `server.py` to serve canonical values as primary, with legacy as fallback

---

## What we are explicitly not doing yet

- **No new website scraping.** The legacy scraper handles all external site access. The canonical pipeline reads its output files.
- **No public cutover.** Users continue to see legacy values. Shadow mode is internal diagnostics only.
- **No new trade API.** The blueprint describes package adjustment, lineup impact, and fairness bands. None of this exists as code. The current trade calculator is pure client-side arithmetic.
- **No player trend tracking.** No historical value data is stored. Each canonical snapshot is a point-in-time replacement, not a time series.
- **No mobile-specific features.** The frontend is responsive but there are no mobile navigation, touch gesture, or PWA features.

---

## For technical details

| Topic | Document |
|-------|----------|
| Full codebase walkthrough | `HANDOFF.md` |
| What the blueprint says vs what exists | `docs/status/master-implementation-audit.md` |
| Source-by-source integration status | `docs/status/canonical-source-matrix.md` |
| Recommended execution sequence | `docs/status/priority-roadmap.md` |
| Which planning docs to trust | `docs/status/blueprint-source-of-truth.md` |

---

_This document reflects the actual state of the codebase, not the intended state. If something is described as "not started" or "empty," that's because the code literally doesn't exist, not because it's planned and pending._

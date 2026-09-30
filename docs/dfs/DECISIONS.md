# DFS — decisions

ADR numbers are local to this file (cite as `docs/dfs/DECISIONS.md ADR-DFS-00N`).

## ADR-DFS-001 — MILP solver: HiGHS via `scipy.optimize.milp` (2026-09-30)

**Context.** The runtime had no numeric stack (no numpy/scipy/PuLP/OR-Tools). A DFS lineup is an
assignment problem with salary, team, game and user constraints; later phases (simulation) will
need numpy regardless.

**Options.** (a) hand-written branch-and-bound — exact only if proven, and dominance pruning is
unsound under team/game/uniqueness constraints; (b) PuLP + bundled CBC (EPL, ships a binary);
(c) SciPy's HiGHS interface (BSD/MIT, wheels for 3.9–3.13, maintained, `mip_rel_gap=0`
certifies optimality, time limits built in).

**Decision.** (c). Imported lazily inside the solver so server start-up is unaffected. Pins
`numpy~=2.0`, `scipy~=1.13`. Every solver answer is re-checked by an independent pure-Python
validator, and brute-force enumeration tests pin exact agreement on small pools.

**Consequence.** Adds ~60 MB of wheels to the venv. If the box cannot install them the API answers
`503 SOLVER_UNAVAILABLE`, never a fabricated lineup.

## ADR-DFS-002 — Readiness is per platform × sport × format × rule version

`not_implemented` → `research_only` (encoded, unverified) → `money_ready` (rules **and** export
verified with cited evidence). The loader refuses `verified` without evidence. `mode: "money"`
fails closed with `RULESET_UNVERIFIED`. A slate imported under a superseded version answers
`RULESET_SUPERSEDED` rather than being re-read under new rules.

## ADR-DFS-003 — Multi-lineup builds are sequential and say so

Lineup *k* maximizes projection subject to uniqueness vs 1..k-1 and exposure caps. That is a
construction method, not a jointly optimized portfolio (Phase 5). Exposure caps are
`floor(pct × N)`; locked players are exempt from the global cap. A shortfall returns the lineups
built plus the isolated conflict; nothing is relaxed to reach N.

## ADR-DFS-004 — Platform season average is opt-in and labelled

A salary file's average is a past observation, not a forecast. It is used only where the owner
ticks the box, stamped `projection_source: platform_season_average`, and shown with an "avg" mark.
DraftKings publishes no games-played count, so an average of exactly 0 is treated as missing.

## ADR-DFS-005 — DFS is its own nav group and skips the dynasty data prefetch

"DFS" is a separate product family; mixing it into Rankings/Trades would imply its numbers are
dynasty value. `/dfs` is on `NO_PLAYER_DATA_ROUTE_PREFIXES`, so the shell does not fetch the
multi-MB dynasty contract there. Future DFS surfaces join this group, not new top-level entries.
Adding a seventh top-level group is the owner's explicit instruction (§4 "available through the
application's normal navigation"); desktop top-bar fit needs visual verification at 1024 px.

## ADR-DFS-006 — Domain isolation is tested, not promised

`src/dfs/` may not import `src.api.data_contract`, `src.canonical`, `src.consensus_edge`,
`src.trade`, `src.bdvm`, `src.league_intel` or `src.model_registry` (AST test). Storage is
`data/dfs/` only. Seasonal/dynasty evidence may be shared later only through a typed contract.

## ADR-DFS-007 — Identity joins are exact within a slate

Projection rows join by platform ID, else by `name_clean.normalize_player_name` + team (+ position).
Ambiguous and disagreeing rows are quarantined. Cross-provider canonical identity (Phase 3) must
extend `src/identity/`, not create a DFS-local matcher.

## ADR-DFS-008 — Contests: separate dimensions, integer cents, nothing assumed (2026-09-30)

A contest's roster format, entry restriction (`maxEntriesPerUser`), guarantee status and payout
shape are independent fields; the shape (`head_to_head` / `fifty_fifty` / `double_up` /
`multiplier` / `tournament`) is DERIVED from the ladder and is descriptive only. Money is integer
cents end to end (Decimal at the edges, never float). The tie rule defaults to `unknown`, which
makes tied payouts unavailable rather than assuming split-positions; a non-whole-cent split is
returned as an exact fraction because the platform's rounding is unverified. An underfilled
contest is an `overlay` only when `guaranteed is True` and prizes exceed fees actually collected.
The entry cap is a hard constraint that needs an explicit spend limit; the recommended count is a
separate, still-unavailable answer. Contests are versioned per owner (append-only), so builds can
later cite the exact version they were evaluated against.

## ADR-DFS-009 — Slates come through adapters into one canonical model; no unofficial endpoints (2026-09-30, owner addendum)

`src/dfs/slate.py::CanonicalSlate` is the only slate shape downstream code reads. Adapters map
into it: official platform files (auto-detected from their own header, position set and roster
labels) and licensed feeds (`src/dfs/providers.py`). Unofficial DraftKings / FanDuel endpoints,
scraping and account automation are never a production dependency. A provider's schema being
PUBLISHED is recorded as `documented`, never `verified`; only observed data with evidence
promotes a cell. The SportsDataIO adapter reuses the repo's existing `SPORTSDATAIO_API_KEY`
header convention and is flag-gated OFF. Detection refuses rather than guesses: ambiguous
position sets are `UNSUPPORTED_SLATE`, a file for another platform is `CSV_WRONG_PLATFORM`, a
recognised-but-unencoded combination (MMA, Showdown, NBA, NHL today) is `UNSUPPORTED_FORMAT`
with what was recognised. The platform's own per-player roster slots are cross-checked against
the encoded rule set and any disagreement is shown, never auto-resolved — that is how an
unverified rule set accumulates evidence.


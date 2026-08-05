# W01 — Feature-name reconciliation

User vocabulary (as given in the audit brief) → the surface that actually
implements it. Decisive: several of these have no route at all.

Measured 2026-08-04 against HEAD `e96c06ef`, the running stack, and
`frontend/lib/nav-model.js`.

| User's name | Nav label today | Page | Backend route(s) | Status |
|---|---|---|---|---|
| **Rankings** | "Rankings" | `/rankings` | `GET /api/data` (via `/api/dynasty-data`), `POST /api/rankings/overrides?view=delta` | Implemented and verified |
| **Trade Calculator** | "Trade Calculator" | `/trade` | `POST /api/trade/simulate`, `POST /api/trade/simulate-mc`, `POST /api/trade/suggestions`, `POST /api/trade/export-ktc`, `POST /api/trade/import-ktc`, `POST /api/bdvm/trade-eval` | Implemented and verified |
| **Edge Finder** | — | — | — | **No surface by that name.** Nearest: `/edge`, labelled **"Source Disagreement"** since the #626 IA rename. Nothing in the tree is called "Edge Finder". |
| **Angle** | "Package Builder" | `/angle` | `POST /api/angle/packages` | Implemented (renamed). **`POST /api/angle/find` is dead** — bridge route exists, no UI caller. |
| **League** | "Hub" (group "League") | `/league` (+ `/league/activity`, `/league/insider-trading`, `/league-comparison`) | `GET /api/public/league*`, `GET /api/league/articles`, `GET /api/league-comparison` | Implemented and verified |
| **IDP Lab** | — | — | — | **Missing.** Zero occurrences of "IDP Lab" anywhere in the repo (code, config, docs, tests). Not renamed — never built. |
| **Settings** | "Settings" | `/settings` | `GET/PUT /api/user/state`, `GET/PUT /api/custom-alerts`, `GET /api/admin/guest-passes`, `POST /api/ros/refresh` | Implemented and verified |
| **More** | "All destinations" | `/more` | none (pure client render of `NAV_MODEL`) | Implemented and verified — it is a site map derived from `nav-model.js`, so it structurally cannot list `/finder`, `/design` or `/intel`. |
| **Roster Analyzer** | — | — | — | **No surface by that name.** Two disjoint things carry the substance: `/rosters` ("Team Strength", `GET /api/terminal` + `GET /api/ros/team-strength`) and `GET /api/gameplan` — a full roster-intelligence engine (`src/roster_intel/`: needs, five-state competitive window, two target engines, partner model, Pareto package frontier) with **no UI caller anywhere**. See W01-F002. |
| **Trade Finder** | "Arbitrage" | `/arbitrage` | `POST /api/trade/finder` | Implemented (renamed). The page's own header comment records that `src/trade/finder.py` had **no** UI caller until `/arbitrage` shipped. |
| **Waivers** | "Waivers" | `/waivers` | `POST /api/waiver/faab-recommend` | Partially implemented. **`POST /api/waiver/suggestions` is dead** — CLAUDE.md concedes "no UI caller"; `/waivers` computes client-side from contract rows. |
| **ROS** | — | — | `GET /api/ros/player-values`, `/api/ros/team-strength`, `/api/ros/status`, `/api/ros/sources`, `/api/ros/health`, `/api/ros/pick-projections`, `POST /api/ros/refresh` | **No top-level page or nav entry.** Seven backend routes, surfaced only as fragments: `/tools/ros-data-health` (admin-only nav), the `PlayerPopup` modal, `RosTradeFitPanel` on `/trade`, and one section of the `/league` hub. A user cannot navigate to "ROS". |
| **Buy/Sell Tracker** | — | — | — | **Ambiguous — two surfaces answer to it, neither uses the name.** `/market/sharp-tracker` ("Sharp Tracker", `GET /api/sharp/market`) is the buy/sell tracker; `/consensus-edge` ("Consensus Edge", `GET /api/consensus-edge/*`) is the buy/sell *board*. Nothing is labelled "Buy/Sell Tracker". |
| **Consensus Edge** | "Consensus Edge" | `/consensus-edge` | `GET /api/consensus-edge/{players,top,methodology,health}` | Implemented, flag-gated OFF (`consensus_edge`, ADR-023). Proven reachable: booting with `RISKIT_FEATURE_CONSENSUS_EDGE=1` returns a real 325-player board (`flag-differential.md`). `GET /api/consensus-edge/health` and `/player/{key}` have no UI caller. |
| **Sharp Tracker** | "Sharp Tracker" | `/market/sharp-tracker` | `GET /api/sharp/market`, `GET /api/sharp/cohort` | Implemented and verified. `GET /api/sharp/market/audit` has no UI caller. |
| **Insider Trading** | "Insider Trading" | `/league/insider-trading` | `GET /api/intel/summary`, `GET /api/intel/player`, `POST /api/intel/leads` | Blocked by data — `data/intel/` and the platform ledger DB are absent in this container. `GET /api/intel/member/{owner_id}` and `GET /api/intel/waiver-interest` have no UI caller at all. |
| **Draft** | "Draft Board" | `/draft` | `GET /api/draft-capital`, `GET /api/sleeper/draft/picks`, `GET /api/ros/pick-projections`, `GET /api/data` | Implemented and verified |
| **Player pages** | — | `/league/player/[playerId]` only | `GET /api/public/league/player/{player_id}` | **Partially implemented.** A real player page exists **only inside the public-league subtree**. There is no private/authenticated player page: on `/rankings`, `/trade`, `/waivers` etc. a player opens `components/PlayerPopup.jsx`, a modal — no URL, not linkable, not shareable, not indexable. |
| **Team pages** | — | `/league/franchise/[owner]` only | `GET /api/public/league/{section}` | **Partially implemented.** Same shape as player pages: a franchise page exists only in the public-league subtree. The private side has `/rosters` (a table of all 12 teams) and `useTeam`, but no per-team URL. |

## Renames that changed the vocabulary

`frontend/lib/nav-model.js` documents a deliberate rename pass (#626). The
brief's vocabulary predates it:

| Old name (brief) | New label | Route |
|---|---|---|
| Arbitrage Finder | Arbitrage | `/arbitrage` |
| Counter-Pitch | Package Builder | `/angle` |
| Signal Blotter / Finder | *merged into* Rankings → "Screens" dropdown | `/finder` → `/rankings` shim |
| Intel (catch-all group) | split into Market + League groups | `/intel` → 308-equivalent redirect to `/league/insider-trading` |
| Edge | Source Disagreement | `/edge` |

The naming rule in `nav-model.js` ("a leaf's label is the SAME string as
the page's `<h1>` and `pageTitleFor`'s answer") **holds**: all 20 static
page `PageHeader title=` values match their nav labels exactly (verified
by grep across `frontend/app/*/page.jsx`).

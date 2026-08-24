# V1-45 — Trade Calculator: exact L4 evidence recipe + two measured consumption gaps

**Row:** `V1-45` — Trade calculator — declared target **L4** — status
`IMPLEMENTED_UNVERIFIED` — owner status *"ALREADY COMPLETE — VERIFY ONLY"*.

**Audited against:** `main` @ `131abf9f`, 2026-08-24, by the Trade Intelligence
lane. Read-only audit — **this document changes no code.**

**Why this document exists.** V1-45's remaining bar is L3 (deployed-SHA
checklist) + L4 (*proof the intended surface consumes the canonical
implementation truthfully*). L3 needs deploy access this lane does not have.
But the L4 clause is partly a **code** question — *does the surface consume the
canonical implementation?* — and that half was measurable from here. It was
measured, and the answer is **no, for two canonical blocks**.

---

## 1. What was measured, and what it proves

`src/api/trade_simulator.py::simulate_trade` stamps exactly three optional
canonical blocks onto the `/api/trade/simulate` response. Repo-wide frontend
consumer counts (excluding `node_modules`):

| canonical block | owner row | frontend consumers | rendered on `/trade`? |
|---|---|---|---|
| `rosterCapacity` | `V1-39` / `C3-CAP-01` | 2 | **yes** (`trade-sections.jsx:322+`) |
| `teamImpact` | `C2-STR-01` | 1 | yes |
| `finalRosterSimulation` | `V1-42` / `C2-SIM-01` | **0** | **no** |

Separately, the Analyze Trade recommendation:

| surface | status |
|---|---|
| `src/trade/analyze_trade.py` | present on `main` |
| `POST /api/trade/analyze` (`server.py:12619`) | present on `main` |
| Next bridge route under `frontend/app/api/trade/` | **absent** (only `finder`, `import-ktc`, `suggestions`) |
| any frontend caller of `trade/analyze` | **zero** |

Endpoints the frontend actually calls: `simulate` (4), `finder` (4),
`import-ktc` (3), `suggestions` (2), `simulate-mc` (1), `export-ktc` (1).
**Never `analyze`.**

### Reproduce (read-only, ~5 seconds, no network)

```bash
# the three canonical blocks the simulator stamps
grep -n 'response\["' src/api/trade_simulator.py \
  | sed 's/.*response\["\([a-zA-Z]*\)".*/\1/' | sort -u

# consumer count per block
for k in teamImpact finalRosterSimulation rosterCapacity; do
  printf "%-24s %s\n" "$k" \
    "$(grep -rl "$k" frontend/ 2>/dev/null | grep -v node_modules | wc -l)"
done

# Analyze Trade reaches no caller
grep -rn "trade/analyze" frontend/ 2>/dev/null | grep -v node_modules
grep -rhoP "api/trade/[a-z-]+" frontend/ 2>/dev/null \
  | grep -v node_modules | sort | uniq -c | sort -rn
```

---

## 2. Attribution — what this is NOT

This is stated carefully because the tempting conclusion is wrong.

* **`V1-42` is NOT reopened.** Its declared target is **L2** (measured
  board/contract effect). Its bar was the engine plus the live endpoint
  wiring, and both hold: `simulate_final_legal_roster` is composed into
  `/api/trade/simulate` and is test-pinned. Frontend rendering is an **L4**
  clause, above V1-42's bar. `V1-42` stays `VERIFIED` and frozen.
* **`V1-43` is NOT reopened.** Its declared target is **L1** (deterministic
  RED→GREEN + green CI). The module and endpoint exist and are tested.
  Reaching a user is an **L4** clause, above V1-43's bar. `V1-43` stays
  `VERIFIED` and frozen.
* **`V1-97` is NOT reopened** — already `VERIFIED`; broader historical trade
  replay is POST-V1.

**Both gaps belong to `V1-45`,** whose target level is the only one in this
group that reaches L4 and therefore the only one whose bar the unrendered
blocks actually fail.

The gap class is *identical* to the one already found and repaired on this
same row: `rosterCapacity` was genuinely computed and rendered by **zero**
frontend files until V1-45's earlier pass wired it into `SimulationPanel`
(merged in `#1025`). Two more canonical blocks are in that same state now.

---

## 3. Exact repair scope (frontend lane — NOT done here)

The Trade Intelligence lane does not own frontend. Scope is stated so whoever
does can execute it without re-deriving the audit.

**R1 — render `finalRosterSimulation` on `/trade`.**
Display-only, mirroring the existing `rosterCapacity` block in
`frontend/app/trade/trade-sections.jsx`. The backend already distinguishes
three states and each must render differently — collapsing them re-creates the
"unknown reads as healthy" defect:
- `{"available": False, "unavailableReason": "capacity_uncertain"}` — taxi
  membership unknown, so the forced-drop set is a **range**; render the
  uncertainty, never a determined lineup.
- `{"unavailable": "<ExcType>"}` — computation failed; say so.
- a populated `RosterSimulation.to_dict()` — `strengthBefore` / `strengthAfter`
  / `promotions` / `displacements` / `cleanupApplied` / `cleanupIsUpperBound`.

No trade math in the component: it is a materializer over backend-stamped
fields, the same relationship `fillLineup` has with `optimalLineup`.

**R2 — decide whether Analyze Trade ships to users in V1.**
This is a **product decision, not a defect**, and is explicitly *not* being
made here. Either:
- (a) add a Next bridge route `frontend/app/api/trade/analyze/route.js` plus a
  display-only panel, and V1-45's L4 clause covers it; or
- (b) record that Analyze Trade is a backend contract in V1 whose consumer
  surface is the POST-V1 CE-05 Trade Desk, in which case V1-45's L4 clause
  should say so explicitly rather than leaving a live endpoint no page calls.

Option (b) is legitimate — `docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md`
§D names CE-05 as the synthesis's natural home. What is *not* legitimate is
leaving it unstated, because "endpoint exists" and "users can see it" then read
the same.

---

## 4. The L3 half — what this lane structurally cannot do

L3 is a deployed-SHA checklist and L4's remaining half is production
observation. Both need deploy/production access this lane does not have.
Recipe for whoever does:

1. Confirm the deployed SHA contains the merge that carries R1 (and R2 if
   taken): `curl -s https://<host>/api/status` and match against `main`.
2. On the deployed `/trade`, build a trade that **forces a release** on a
   roster at the 58-man cap (six of twelve `dynasty_main` rosters sat at the
   cap on 2026-08-18, so this is reachable with real data), and confirm the
   rendered forced-drop set and the re-solved lineup match
   `/api/trade/simulate`'s `finalRosterSimulation` for the same payload.
3. Confirm the three uncertainty states above render distinguishably —
   in particular that `capacity_uncertain` does **not** render as "no drops
   required".
4. Only then is V1-45 promotable, and the promotion is Claude 5's.

---

## 5. Status

| item | state |
|---|---|
| L1 / L2 (code + measured effect) | already evidenced on this row |
| L4 clause — surface consumes canonical | **FAILS** for `finalRosterSimulation`; **undecided** for Analyze Trade |
| L3 — deployed-SHA checklist | not runnable from this lane |
| repair R1 | scoped, not implemented (frontend lane) |
| decision R2 | open product question for the owner |

`V1-45` therefore stays `IMPLEMENTED_UNVERIFIED`. This document does not
promote it and does not edit the V1 ledger.

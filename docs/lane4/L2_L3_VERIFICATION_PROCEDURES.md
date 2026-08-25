# Lane 4 — executable verification procedures (L2 / L3)

**What this is.** The exact checklist for each Lane 4 item that
`docs/VERSION_1_COMPLETION_CONTRACT.md` requires at **L2** or **L3**, written so
that whoever holds production credentials can execute it without re-deriving
what counts as proof.

**What this is not.** It is not evidence. Nothing here is a claim that any item
has been verified. Running a procedure produces evidence; writing one down does
not.

Levels, quoted from the contract §2 so this file cannot drift from it:

| level | what satisfies it |
|---|---|
| **L1 — deterministic** | RED→GREEN test at exact head, plus green CI on the merge tree |
| **L2 — board/contract inert or measured** | L1 plus a measured statement of the effect on the live board or contract (0 rows, or the exact rows) |
| **L3 — production** | L1 plus the named checklist executed against the **deployed SHA**, evidence recorded |
| **L4 — production consumer** | L3 plus proof the intended user-facing surface consumes the canonical implementation with truthful semantics |

**Two rules that bind every procedure below.**

1. **No production authentication is bypassed.** Where a step needs a session
   the environment does not have, the procedure says so and stops. An
   unauthenticated `401` is recorded as `unverifiable_unauthenticated` — it is
   never rewritten as a pass, and never worked around.
2. **No cohort, ledger or roster is manufactured to make a check succeed.**
   A step whose input does not exist yet is `BLOCKED` with the missing input
   named. Synthesising the input would verify the synthesis.

---

## Corrected 2026-08-19, and now executable

This document shipped with **four wrong references**, found by deriving every
endpoint and field from the actual route registrations and response producers
rather than from memory. Each is corrected in place below and called out where
it occurs, because a superseding document leaves the wrong one in circulation.

| # | this document said | reality |
|---|---|---|
| 1 | `POST /api/faab/recommend` (×2) | **`POST /api/waiver/faab-recommend`** — there is no `/api/faab/*` prefix at all, so **every crowd-market step was unrunnable** |
| 2 | roster-percentage → `sources.ffpc.status` | **`coverage.platforms.ffpc.status`**, and it is on **`/api/sharp/market`** — wrong field *and* wrong endpoint |
| 3 | `cohortCoveragePct` (under `cohort`) | **`transparency.cohortCoveragePct`** |
| 4 | roster-percentage → `rostersObserved` | **does not exist**; the count is `transparency.eligibleRosters` (also `sample.eligibleRosters`) |

Correct and left alone: `cohort.selectedManagers` (present on **both** boards),
`crowdMarket.{state,refusalReason,excludedCounts,tierCounts,pricesIdp,rowsUsed,rowsTotal,targetFormatUnknown,playerHasEvidence}`,
`contention.notes`, and `CollectResult.status`. Two further values were wrong
and are fixed at their rows: the `/api/status` SHA fields (next section) and the
`unavailable_reason` literals (V1-60).

**The reason this happened is worth keeping.** A prose checklist's paths are
checked by a reader's goodwill; nothing fails when one is wrong, and an
unrunnable procedure reads exactly like a runnable one until someone with
production credentials wastes an evening on it.

So the checklist is no longer the only artifact. **`scripts/verify_lane4_production.py`**
resolves every route and field against the deployed code at run time, and
`tests/ops/test_lane4_verification.py` asserts — against the real producers, at
every CI run — that each route this package names is registered and each field
path exists. One of those tests scans **this document** and fails if it names a
route that does not exist. That is what would have caught all four.

The verifier reports five states, and three of them are not passes:

| status | meaning |
|---|---|
| `pass` | the case arose and behaved correctly |
| `fail` | the case arose and behaved incorrectly |
| `unmeasurable` | the input was read; the case did not arise |
| `blocked` | a required input does not exist here |
| `unverifiable_unauthenticated` | 401/403 — insufficient evidence |

**Exit `0` is reserved for a COMPLETE run.** Any blocked, unmeasurable or
unauthenticated check caps the run at exit `3`, however many others passed, and
a `pass` whose denominator is `0` is downgraded automatically — a check that
inspected nothing cannot report success.

---

## Deployed-SHA preamble (every L3 procedure)

An L3 result is only meaningful against a known commit.

> **CORRECTED 2026-08-19 — the deployed SHA is NOT observable over HTTP.**
> This section previously said to record a `commit` field and a `startedAt`
> field from `/api/status`. **Neither exists.** Verified against the producer
> (`server.py::get_status` + `_scrape_status_payload`): the payload carries
> `contract`, `data_runtime`, `health`, `sources`, `source_failures` and the
> payload-size block, and its `contract.version` is the **API data-contract**
> version (e.g. `2026-03-10.v2`) — the payload's shape, not the commit that
> produced it. **No endpoint publishes a git SHA or build identifier.**

So an L3 run's tree identity must come from the box, not the API:

```bash
# ON THE BOX — the only place the SHA is knowable
git -C "$APP_DIR" rev-parse HEAD
git -C "$APP_DIR" log -1 --format='%H %ci %s'

# from anywhere — useful context, but NOT a tree identity
curl -s https://chaseupside.com/api/status | python -m json.tool | head -40
```

Record: the `git rev-parse HEAD` output, `contract.version`,
`data_runtime.last_data_refresh_at`, and the wall-clock time of the call. Every
artifact below is filed under that SHA.

**`scripts/verify_lane4_production.py` encodes this gap rather than papering
over it:** in `--mode remote` it stamps `headSha: null` with
`headShaSource: "unavailable_over_http"`, and only `--mode onbox` can answer it.
Closing the gap properly means publishing a build identifier, which is a Lane 5
change and is not proposed here.

---

## V1-57 — FAAB bid-history collection is scheduled, not a manual step (L3)

The unit is `dynasty-faab-history` (daily, 07:40 UTC, `RandomizedDelaySec=600`,
`Persistent=true`), installed by `deploy/install-systemd-service.sh` via
`install_simple_timer "faab-history"`.

#920 moved this row to `IMPLEMENTED_UNVERIFIED`: the scheduler exists and was
verified in the diff, and what L3 still needs is **the unit installed and
firing on prod**. That is exactly the checklist below, and it is not claimable
from a repository.

**Do not confuse it with `dynasty-crowd-faab`.** That one collects what OTHER
leagues pay; this one collects what THIS league pays, and it is what the market
priors are fitted from. Verifying one says nothing about the other.

On the box:

```bash
systemctl list-timers 'dynasty*faab*' --all
systemctl status  dynasty-faab-history.timer
systemctl status  dynasty-faab-history.service
journalctl -u dynasty-faab-history.service --since '-8 days' --no-pager | tail -60
ls -la /opt/dynasty/data/faab/          # path per the deployed APP_DIR
```

| assertion | pass |
|---|---|
| the timer is installed and enabled | `LOAD=loaded`, `ACTIVE=active`, and a `list-timers` row whose `UNIT` ends `-faab-history.timer`. The prefix is `$SERVICE_NAME` from `install-systemd-service.sh` (`install_simple_timer` builds `${SERVICE_NAME}-${stem}`), so match on the **suffix** rather than assuming `dynasty-` |
| it has actually fired | `LAST` is populated and within ~25 h of now |
| the run succeeded | the most recent journal entry exits **0** (1 = registry unreadable, 2 = nothing fetched) |
| it produced the artifact | `data/faab/bid_history_<leagueKey>.json` exists per active league, `mtime` inside 25 h |
| the artifact is used | `POST /api/waiver/faab-recommend` → `contention.notes` does **not** carry the configured-priors fallback note |

**Exit 2 is not a pass and not a failure.** It means nothing was fetched and the
previous file was left untouched. Record it as `DEGRADED` with the prior file's
`mtime`, because stale own-league priors and no own-league priors are different
states.

**Scheduling is the requirement; a green manual run does not satisfy it.** A
one-off `python scripts/fetch_faab_history.py` proves the script works, which
was never the open question.

---

## V1-129 — external crowd-FAAB evidence is comparable, fresh and position-capable (L2)

Four separately-refusable behaviours. Each needs its own recorded answer; a
single "the endpoint returned 200" satisfies none of them.

L2 wants a measured statement, so every row below is a count, not a yes/no.

### 129a — new crowd rows carry comparability provenance

```bash
python - <<'PY'
import json, pathlib, collections
p = pathlib.Path("data/faab/crowd_history_dynasty_main.json")
d = json.loads(p.read_text())
rows = d["rows"]
have = [r for r in rows if isinstance(r.get("comparability"), dict)]
print("updatedAt:", d.get("updatedAt"))
print(f"rows={len(rows)} with comparability={len(have)}")
print("tiers:", collections.Counter(r["comparability"].get("tier") for r in have))
print("settings present:", sum(1 for r in rows if isinstance(r.get("settings"), dict)))
PY
```

PASS: every row written **since #911 deployed** carries a `comparability` block
and a `settings` block. Rows older than that deploy legitimately carry neither.

### 129b — legacy rows are honestly excluded, not silently counted

The ledger is accumulated, so pre-#911 rows persist — and they are **hard
excluded**, not softly labelled. This is the corrected reading (`main`,
2026-08-19): the old fetcher's own predicate dropped rows whose `superflex` or
`tep` was `None`, so every stored legacy row *has* readable format evidence,
reaches `classify()`, and is refused there on `budget_unknown` +
`roster_exclusivity_unknown` — it records neither `originalBudget` nor
`rostersPerPlayer`, and both are required, fail-closed. The `unverified` branch
exists for a row with no readable settings at all, which no legacy row is.

PASS: the legacy rows appear in `excludedCounts` under `budget_unknown` and
`roster_exclusivity_unknown`, and in **no** A/B/C tier.

**Expect `crowdMarket.state: "missing"` from deploy, and do not read it as a
regression.** With `CROWD_RETENTION_DAYS` at 120 the whole accumulated ledger
goes unusable at once, and `merge_crowd_rows` is existing-wins so it never
self-heals. Re-priming is a fetch (`dynasty-crowd-faab`), not a policy change,
and it takes roughly the feed's ~5-day rolling window to rebuild. **The gate is
correct and must not be relaxed to clear this** — a refusal is not a wrong
number.

FAIL, and this is the trap worth naming: legacy rows counted in an A/B/C tier,
or `rowsUsed == rowsTotal` on a ledger that still holds pre-#911 rows. That is
unprovable evidence passing as verified, and it looks identical to a clean
ledger.

### 129c — an offense-only population refuses to price an IDP claim

```bash
curl -s -X POST https://chaseupside.com/api/waiver/faab-recommend \
  -H 'content-type: application/json' -b "$SESSION_COOKIE" \
  -d '{"leagueKey":"dynasty_main","addPlayerName":"<a rostered LB>"}' \
| python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d["crowdMarket"], indent=2))'
```

> **CORRECTED 2026-08-19.** This block said `POST /api/faab/recommend`, which is
> not a route — there is no `/api/faab/*` prefix at all. The real registration
> is `@app.post("/api/waiver/faab-recommend")` in `server.py`. Both occurrences
> in this document were wrong, so **every crowd-market step here was
> unrunnable**.

PASS: `pricesIdp: false` **and** `refusalReason: "population_cannot_price_idp"`
**and** `playerHasEvidence: false`.

The gate reads what the retained rows contain, so `pricesIdp: true` is not a
failure — it means an IDP league entered the feed. Record which league.

### 129d — a stale ledger refuses to price

Do **not** age the file to test this. Read the state that exists:

PASS: `state == "fresh"` with `ageDays <= maxFileAgeDays`, and
`refusalReason: null`; **or** `state == "stale"` with
`refusalReason: "crowd_ledger_stale"` and `playerHasEvidence: false`. Either is
a pass — what fails is a stale ledger that still priced, or a `state` of `fresh`
with `ageDays > maxFileAgeDays`.

`ageDays: null` must read `stale`: unmeasurable freshness is not freshness.

### 129e — the target league can describe itself *(added 2026-08-19)*

New with the card-derived TEP repair, and the one most likely to be red on a
cold deploy.

PASS: `crowdMarket.targetFormatUnknown == []`.

FAIL: it lists `tep`, and `refusalReason` is
`target_format_unverifiable:tep`. That is not a feed problem and the fix is not
in `data/faab/` — the league has no **fresh** scoring card. Remedy:

```bash
python scripts/fetch_league_scoring.py     # writes data/leagues/scoring_<id>.json
```

Then re-read. Record the before/after `rowsUsed`, because this is exactly where
the TEP change moves the admitted population.

**Expect the admitted set to change, and record it rather than treating it as a
regression.** `dynasty_main`'s real 2026 card grants TEs no premium, while its
`superflex_tep15_ppr1` label said it did — so the leagues previously admitted on
a TEP match are now excluded and vice versa. On the shipped synthetic fixture
(`tests/sources/fixtures/ktc_waiver_page.html`, 12 rows) the comparable count
goes **3 → 1**; the production number must be read off the real ledger.

---

## V1-60 — FFPC roster lane real or honestly empty (L2)

The requirement is a **truthful degraded state**. Zero rosters because FFPC is
switched off and zero rosters because the collection broke must not render
identically, and neither may read as "we looked and nobody owns him".

> **CORRECTED 2026-08-19 — three field paths here were wrong, and one field
> did not exist.** Verified by building both real payloads and walking them:
> the FFPC status block is on **`/api/sharp/market`**, not this board; the
> population counts live under **`transparency`**, not `cohort`; and
> `rostersObserved` (named elsewhere in this file's V1-65 step) exists nowhere.
> `cohort.selectedManagers` is correct and is present on **both** boards.

Two payloads, because the two facts live on different endpoints:

```bash
# population counts + coverage
curl -s 'https://chaseupside.com/api/sharp/roster-percentage' -b "$SESSION_COOKIE" \
| python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"status": d.get("status"), "cohort": d.get("cohort"), "transparency": d.get("transparency"), "sample": d.get("sample")}, indent=2))'

# per-platform lane status
curl -s 'https://chaseupside.com/api/sharp/market?window=30d&limit=1' -b "$SESSION_COOKIE" \
| python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d["coverage"]["platforms"], indent=2))'
```

| assertion | pass |
|---|---|
| the platform block states FFPC's status | **`coverage.platforms.ffpc.status`** (on `/api/sharp/market`) ∈ `disabled` / `degraded` / `no_data` / `ok`, never absent. **Not** `sources.ffpc.status`, and **not** on the roster-percentage board |
| a disabled lane says disabled | `coverage.platforms.ffpc.enabled: false` when no roster-bearing URL is configured |
| coverage is unavailable, not zero | **`transparency.cohortCoveragePct`** is `null` — never `0` — when no roster was observed. It is **not** under `cohort` |
| the population is stated beside it | `transparency.cohortManagers`, `transparency.cohortManagersRepresented`, `transparency.eligibleRosters`, `transparency.ffpcRosters`, `transparency.sleeperRosters` |
| a skipped collection names itself | `CollectResult.status == "unavailable"` (the constant is `roster_collect.STATUS_UNAVAILABLE`) with an `unavailable_reason` of **`skipped_by_caller`** or **`no_cohort_managers_on_platform`** — the literal values of `UNAVAILABLE_SKIPPED` / `UNAVAILABLE_NO_MANAGERS`. This row previously named them `skipped` / `no_managers`, which match nothing |

FAIL: a `0` or `0.0` anywhere a lane was not actually measured. That is the
whole defect this row tracks.

---

## V1-63 — manager-level Sharp concentration (L1)

L1 only: a RED→GREEN test at exact head plus green CI. **No production step is
required and none should be invented** — inventing one would move the bar the
contract set.

Current head ships the person-level concentration safeguard
(`src/sharp/consensus.py`) with `networkConcentration`, `networkCount`,
`weightedPersonNet`/`Volume`, `personVotes`, `mixedPersonSignals`,
`personAgreement` and `personManagerQuality`.

```bash
python -m pytest tests/sharp/test_person_consensus.py tests/sharp/test_curated_wiring.py -q
```

PASS: green, **and** the four undefined-state tests are present and were shown
RED before the fix that made them green:

- zero voters → `personManagerQuality is None`
- a measured `0.0` → stays `0.0`
- ≥ 1 voter → the actual mean
- no weighted volume → `networkConcentration is None`

plus the consumer guard (no module coerces an undefined person quantity back to
a number) and its meta-test (the scanner matches the shapes it exists to catch).

**This row names the defect directly.** #920 moved V1-63 to
`IMPLEMENTED_UNVERIFIED` with: *"Not VERIFIED: `personManagerQuality` still
returns `1.0` for zero voters, the same defect two lines away."* That is the
repair above, so the stated blocker to `VERIFIED` is discharged at this head.

**Open, and not claimed closed:** whether `inv 4.6` is satisfied by the
person-level block or additionally requires a *manager*-level concentration
figure is an owner/Integration reading, not mine to declare. Nothing here adds
a field — this repairs the semantics of fields that exist.

---

## V1-64 — Sharp event ledger surfaces adds/drops (L1)

L1 only.

```bash
python -m pytest tests/sharp/test_transactions.py tests/sharp/test_unified_market.py -q
```

PASS: green, and `/api/sharp/market` rows carry `buys`, `sells`, `net`,
`volume`, `movementCount`, `tradeCount` as **raw counts** alongside the weighted
view — the audit trail is not replaced by the capped weights.

Also assert the phantom-row guard (`2026-08-19`): a movement whose action is
neither `add` nor `drop` must produce **no** asset row, rather than a row with
zero movements and `managerQuality: 1.0`.

---

## V1-65 — Insider Trading / cross-league ownership (L2)

Contract note: *"complete, consolidation pending"*. The L2 statement is
therefore about the **cohort definition**, which is where a duplicate would
show up.

```bash
python -m pytest tests/sharp -q
grep -rn "def cohort_members" src/ | grep -v __pycache__
```

PASS: exactly **one** definition of `cohort_members`
(`src/sharp/cohort.py`); `market.py`, `roster_percentage.py`,
`roster_collect.py` and `scripts/crawl_sharp_activity.py` all resolve through
it, and none applies a qualification rule of its own.

Measured statement required for L2: the number of cohort members and the number
of roster observations behind the live board, from
`/api/sharp/roster-percentage` — **`cohort.selectedManagers`** and
**`transparency.eligibleRosters`**. (`rostersObserved`, which this line used to
name, does not exist in the payload; `sample.eligibleRosters` carries the same
count beside the 8-roster ranking minimum.)
If both are `0`, that is the honest answer and V1-58 is the blocker — record it
as such rather than as a V1-65 failure.

---

## V1-58 / V1-59 — BLOCKED, and why

Both need production Sharp evidence. The recorded artifacts end at
`401` / `502` / `unverifiable_unauthenticated` from
`https://chaseupside.com/api/sharp/cohort`.

`/api/sharp/*` is **not** in the public-API allowlist
(`tests/sharp/test_public_api_allowlist.py` pins that), so the endpoint requires
an authenticated admin session. That is correct behaviour and must not be
relaxed to make verification easier.

**The single credential that unblocks both:** an authenticated admin session
cookie for `chaseupside.com`, held by the site owner. With it, V1-58 is
`GET /api/sharp/cohort` returning a non-empty membership against the deployed
SHA, and V1-59 is a clean `journalctl` run of the three-pass chain
(`dynasty-sharp-discovery` 04:20 → `dynasty-sharp-records` 04:50 →
`dynasty-sharp-rosters` 05:50) with no FFPC timeout and no SQLite lock.

Without it both stay `BLOCKED`. They are **not** to be closed by standing up a
synthetic cohort: a manufactured population would verify the manufacture.

---

## Lane-4 feature-flag posture (measured 2026-08-24, `main` `131abf9f9`)

**No production step is required and none should be invented.** This is a
structural property of the tree, measurable locally, and it is already guarded.

V1 requires proof that a flag-off surface cannot masquerade as implemented. For
Lane 4 the answer is that **no Sharp or FAAB surface is flag-gated at all** —
zero `is_enabled` call sites exist under `src/sharp/` or in the FAAB modules
(`faab_engine`, `faab_recommender`, `faab_comparability`, `faab_history`,
`faab_contention`, `faab_analytics`). Every one is unconditionally reachable in
the intended production configuration.

```bash
python -m pytest tests/api/test_feature_flag_endpoint_reachability.py -q
```

PASS: green, **and** the three Lane-4 tests are present —
`test_no_sharp_or_faab_surface_is_gated_by_an_unregistered_flag`,
`test_a_lane4_gate_defaulting_off_would_hide_a_shipped_surface`, and the
non-vacuity control `test_the_lane4_gate_scan_can_actually_see_a_gate`.

The control matters: the first two pass over an **empty** gate set, and an empty
set is what a broken scanner also produces. The control asserts the scanner
resolves the known real gate in `src/api/gameplan.py`, so "no Lane-4 gates" is a
measurement rather than a silence.

`te_basis_conversion` transitively reaches `/api/sharp/roster-percentage` and
that is correct — it is Lane 5's canonical-value flag, defaults `True`
(`gate_status == LIVE`), and is not referenced in `src/sharp/` at all. The Sharp
board reaches it by consuming canonical board values.

## V1-89 — measure DraftSharks freshness before acting on `OD-04`

`OD-04` (re-mint / accept degradation / retire) was raised on a ~219 h staleness
against a 24 h threshold. **Check whether that condition still holds before
treating the decision as live** — measured 2026-08-24, all three DraftSharks
keys were **0.9 h** old and every registered source was ≤ 3.0 h.

```bash
# fetch-freshness of every source, straight from tracked state on main
python - <<'PY'
import subprocess, datetime, os
now = datetime.datetime.now(datetime.timezone.utc)
paths = subprocess.run(["git","ls-tree","--name-only","origin/main","data/scrape_state/"],
                       capture_output=True, text=True).stdout.split()
for p in sorted(paths):
    if not p.endswith("_last_success"):
        continue
    key = os.path.basename(p).replace("_last_success", "")
    raw = subprocess.run(["git","show",f"origin/main:{p}"],
                         capture_output=True, text=True).stdout.strip()
    try:
        age = (now.timestamp() - float(raw)) / 3600
    except ValueError:
        age = float("nan")
    flag = "  <== DRAFTSHARKS" if "draftShark" in key else ""
    print(f"{key:26} age_h={age:8.1f}{flag}")
PY
```

**A fresh stamp is NOT a pass on its own.** `config/source_staleness.json` says
in its own header comment that the stamp tracks *"fetch succeeded"*, not
*"vendor published new content"*. So this command answers the **watchdog**
question `OD-04` named; it does not answer content staleness, which remains the
L3 production check. Report the two separately or the row will be closed on the
wrong evidence.

> **Superseded 2026-08-25 by `docs/lane4/V1_89_DRAFTSHARKS_DECISION_PACKET.md`**
> (Integration reconciliation): the packet performs BOTH halves — fetch ages
> AND content freshness measured against the vendor's own publication marker —
> and records the `OD-04` recommendation **A. HEALTHY_CURRENT**. Run the
> packet's procedure rather than this one; this section stays as the record of
> why the two questions are separate.

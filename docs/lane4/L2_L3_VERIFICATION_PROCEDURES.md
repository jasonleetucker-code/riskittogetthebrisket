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

## Deployed-SHA preamble (every L3 procedure)

An L3 result is only meaningful against a known commit. Record this first; if
the SHA does not match the head being claimed, stop — the run proves something
about a different tree.

```bash
curl -s https://chaseupside.com/api/status | python -m json.tool | head -40
```

Record: `commit`/`version` field, `startedAt`, and the wall-clock time of the
call. Every artifact below is filed under that SHA.

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
| the timer is installed and enabled | `LOAD=loaded`, `ACTIVE=active`, `UNIT=dynasty-faab-history.timer` in `list-timers` |
| it has actually fired | `LAST` is populated and within ~25 h of now |
| the run succeeded | the most recent journal entry exits **0** (1 = registry unreadable, 2 = nothing fetched) |
| it produced the artifact | `data/faab/bid_history_<leagueKey>.json` exists per active league, `mtime` inside 25 h |
| the artifact is used | `POST /api/faab/recommend` → `contention.notes` does **not** carry the configured-priors fallback note |

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
curl -s -X POST https://chaseupside.com/api/faab/recommend \
  -H 'content-type: application/json' -b "$SESSION_COOKIE" \
  -d '{"leagueKey":"dynasty_main","addPlayerName":"<a rostered LB>"}' \
| python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d["crowdMarket"], indent=2))'
```

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

```bash
curl -s 'https://chaseupside.com/api/sharp/roster-percentage' -b "$SESSION_COOKIE" \
| python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:v for k,v in d.items() if k!="assets"}, indent=2))'
```

| assertion | pass |
|---|---|
| the source block states FFPC's status | `sources.ffpc.status` ∈ `disabled` / `degraded` / `no_data` / `ok`, never absent |
| a disabled lane says disabled | `enabled: false` when no roster-bearing URL is configured |
| coverage is unavailable, not zero | `cohortCoveragePct` is `null` — never `0` — when no roster was observed |
| a skipped collection names itself | `CollectResult.status == "unavailable"` with an `unavailable_reason` of `skipped` / `no_managers` |

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
`/api/sharp/roster-percentage` (`cohort.selectedManagers`, `rostersObserved`).
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

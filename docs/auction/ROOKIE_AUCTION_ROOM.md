# Rookie Auction Room — feature record

**Status:** IMPLEMENTED → **MOCK READY** (milestone B). Official launch: **OFF**.
State ladder (never collapsed): IMPLEMENTED → MOCK READY → HUMAN REHEARSAL PASSED → LIVE-READY → OWNER LAUNCH APPROVED.

**Authority:** owner directive 2026-09-29 ("Build Chase Upside's shared slow rookie auction room —
mock-first, live-gated") plus the same-day owner clarification "LEADING BIDS RESERVE MONEY".
Extends — does not replace — `docs/OWNER_FEATURE_ADDENDUM_2026-09-13_LIVE_ROOKIE_AUCTION_PERFECT_DRAFT.md`
(manifest `C7-DRAFT-03`, unit `C7-U12`) and `docs/perfect-draft.md`. That addendum's open items
U1 (concurrency limit) and U6 (increments/proxy rules) are now answered by the owner: 12 open lots;
whole-dollar increments with private proxy maxima. Because Chase Upside now HOSTS the auction, the
addendum's "timers, quiet hours and nomination rules stay as the platform defines them" is satisfied
by this room being that platform.

No official draft may be opened, no official invitation distributed, no real roster changed and no
real budget spent without the owner's separate explicit launch approval. The API refuses
`roomType: "official"` outright (`official_launch_gated`).

## 1. Canonical owners

| Concept | Owner |
|---|---|
| Auction rules, money, proxy resolution, timers, completion | `src/auction/engine.py` (pure, deterministic) |
| Active-time calendar (08:00–21:00 America/New_York) | `src/auction/schedule.py` |
| Binding vs proposed rules, presets, confirmation keys | `src/auction/rules.py` |
| Authoritative persistence, idempotency, command/event log, awards | `src/auction/store.py` (`data/auction/auction.sqlite`) |
| Auction identity: accounts, sessions, invites, seats | `src/auction/accounts.py` |
| HTTP surface `/api/auction/*` | `src/auction/api.py` |
| Background closes / bots / heartbeat / outage pause | `src/auction/runtime.py` |
| Budgets, seats, rookie pool (READ ONLY adapters) | `src/auction/sources.py` → `/api/draft-capital`, contract `sleeper.teams`, `src/draft/rookie_pool.py` |
| Pages | `frontend/app/auction/` (lobby, `join`, `[roomId]`), `frontend/lib/auction-client.js` |

Nothing here computes a player value, a draft-capital dollar, or an identity. Budgets are the raw
`teamTotals[].auctionDollars` (never effective auction power, value, or FAAB), joined to Sleeper
seats on `team_name || display_name` = `sleeperTeamName`; an unjoinable seat is `missing`, which
blocks start until the commissioner corrects it (audited). Opening balances freeze at start.

## 2. Rules

Binding owner rules and proposed defaults are listed side by side in `src/auction/rules.py`
(`BINDING_OWNER_RULES`, `PROPOSED_RULE_KEYS`). Mocks run on the proposed defaults. An official room
cannot start until every proposed key is confirmed on the consolidated rule screen, and until its
rookie pool is an approved official class.

### Money — leading bids reserve money (owner clarification 2026-09-29)

```
balance   = opening + adjustments − settled purchases
committed = Σ current public price of every open lot the seat LEADS
spendable = balance − committed
effective(seat, lot) = min(private max, balance − committed on OTHER lots)
```

$50 unspent and leading at $45 ⇒ $5 available elsewhere. A private maximum never executes past what
is affordable at that moment; an unaffordable maximum never sets a phantom price. Being outbid
releases the reservation (and the seat's other conditional maxima may then respond — lowest lot
first, deterministically). Winning converts the reservation into the purchase exactly once. Every
transition runs inside one `BEGIN IMMEDIATE` transaction, so two simultaneous requests cannot spend
the same dollars. Pinned by `tests/auction/test_leading_bid_reservation.py` (the exact example, the
thread race, and restart persistence).

Prices move only when a competitive action moves them. A leader that won a tie while
budget-capped keeps that price when its money frees elsewhere; the next competitive action on that
lot re-resolves with full capacity. `tests/auction/test_engine_fuzz.py` checks, after every command
across 40 random rooms, that a from-scratch re-resolution agrees on every leader and is within this
documented +$1 tie case, that no seat is overspent or overcommitted, that prices never fall, and that
replaying the command log reproduces the room exactly.

### Proxy examples (all tested, `tests/auction/test_engine_proxy.py`)

A nominates at $0 unchallenged → A wins at $0 · a $0-budget manager may nominate · A alone raising to
$50 keeps the price $0 · A $50 vs B $39 → A at $40 · equal $50 → earlier wins at $50 · B $51 → B at
$51 · two $0 maxima → earlier wins at $0 · a $0 offer cannot displace a positive leader · an identical
resubmission is a no-op (no new priority, no extension).

### Time

Clocks count ACTIVE seconds only; deadlines are absolute epochs computed through the calendar, so
20:30 with one hour left closes 08:30 next day and a deadline landing on 21:00 closes at 21:00.
DST, month and year rollover are tested. A public competitive change extends a lot to
`max(deadline, now + 1 active hour)`; a leader's private raise never extends. Every command first
settles everything due at its own server time, so a delayed worker can never create a late-bid
window. Commissioner pause freezes remaining active time; resume recomputes from resume time.

**Outage policy (proposed):** at startup, a running room whose heartbeat is older than
`outage_threshold_seconds` (5 min) is paused AS OF its last heartbeat — nothing that expired while
nobody could reach it is awarded. The commissioner resumes; outage resumes give every open lot at
least one active hour (announced).

### Completion

All money spent (opening pool > 0 and every settled balance $0) ⇒ no new nominations, open lots drain
normally, then COMPLETE. All nomination rights used/passed ⇒ same drain, unspent balances disclosed.
An all-$0 mock never triggers the money-spent end.

### Nomination window (proposed)

The first `free slots` pending rights in (round, order) sequence are on the clock, one per seat. A
right starts its clock only when a slot exists — a full board penalises nobody. Unused turns pass
after 13 active hours (audited). An explicitly authorised private queue may nominate the first
still-eligible queued player at $0 when the turn and a slot arrive; nothing else ever acts for a
manager.

## 3. Identity and security boundary

The site login is a single env-configured owner account plus shared guest passes; it cannot
represent twelve accountable bidders, so the room owns a scoped identity layer and bridges from the
site owner's admin session (`POST /api/auction/auth/site-owner`). Sleeper usernames are handles only;
no Sleeper password is ever requested or stored. Passwords: `hashlib.scrypt` with per-user salt.
Sessions: 256-bit tokens, SHA-256 stored, HttpOnly + Secure + SameSite=Strict, 30-day absolute
expiry, revoked on logout / password change. Invites: commissioner-issued, single-use, expiring,
optionally handle-locked; token stored hashed and shown once. Every mutation requires a same-origin
`Origin` and an `Idempotency-Key`; login is rate-limited by the existing throttle.

Authorization is derived server-side from membership on every request (including after a long-poll
wait). Clients never send an actor, seat or role. Public projections and events never contain a
maximum; seat events reach only that seat. The commissioner is also a bidder and has no view of
anyone's maxima.

**Honest trust boundary:** private maxima are stored server-side in plaintext inside the room state so
the engine can resolve bids. Anyone with operating-system or database access to the production host
(the operator) CAN read them, and so can anyone holding a backup. Room software never exposes them;
the operator boundary is not a cryptographic one. Any operator break-glass action must be recorded
out-of-band until an audited break-glass command exists.

## 4. Storage, recovery, limits

`data/auction/auction.sqlite` (gitignored `data/`, survives deploys), WAL + `synchronous=FULL`.
Acceptance is returned only after COMMIT. Normal restart/crash: zero lost acknowledged actions
(tested: fresh Store over the same file, replay verification). Missing/unreadable store after first
init ⇒ `StoreUnavailable`, every route 503 — never an empty reseed.

Backups: both nightly jobs (`deploy/backup_user_kv.sh`, `deploy/backup/riskit-state-backup.sh`) take
an online SQLite backup of the auction DB. **Recovery point for host/disk loss is the last nightly
backup — up to ~24 h of acknowledged actions could be lost.** That window is acceptable for mocks and
is NOT acceptable for an official draft without explicit owner acceptance or a tighter off-host
cadence (milestone D). Restore drill: `tests/auction/test_api_store.py::test_online_backup_restores_onto_a_fresh_environment`.

## 5. Live delivery

Revision long-poll (`GET /rooms/{id}/view?after=<rev>&wait=25`). Chosen over SSE/WebSockets because
production nginx buffers `/api/` and has a 120 s read timeout: a 25 s long-poll needs no proxy change,
every response is a complete authorised snapshot (no gaps, no replay ordering bugs), and the client
drops any response older than the revision it holds. Commands never wait for valuation, scrapers or
Perfect Draft.

## 6. Mocks

Same engine, same authorization, same ledger, same settlement. Room type is immutable and
server-owned. Mock-only: seeded bots (public information + own seeded preferences, same command
path), virtual clock jumps, clone-to-new-run. A played mock is never promoted.

## 7. Milestones

- **A — rules engine:** DONE.
- **B — first playable persistent mock:** DONE (this record).
- **C — multi-user + Perfect Draft:** invitations/seat permissions/12-user operation are in B; still
  to do: Perfect Draft adapter reading the room's `spendable`/purchases/leading prices/own maxima
  (same available balance as the room — owner clarification), auction-dollar trades, mobile pass.
- **D — notifications & recovery:** Web Push (reuse `src/api/push_delivery.py`) + in-app inbox with
  deadline-revision-keyed last-hour reminders; tighter off-host backup cadence; audited corrections.
- **E — rehearsal & release readiness:** adversarial audit, accelerated full drafts, multi-day real
  clock mocks, owner rule confirmation, launch checklist.

## 8. Unresolved (owner decisions — none block mocks)

Official values for every `PROPOSED_RULE_KEYS` entry; the 2027 points-for nomination order (owner
supplies it; 2026 partial PF is not assumed final); the official 2027 rookie pool; acceptance of the
disaster-recovery window; whether open trade offers reserve money (milestone C).

## 9. Follow-up decision register

| Id | Owner instruction | State |
|---|---|---|
| AUC-001 | Leading bids reserve money (2026-09-29) | IMPLEMENTED + tested (§2 Money); Perfect Draft adapter must read the same `spendable` (milestone C) |
| AUC-002 | Draft notifications: native Web Push, no SMS bill (2026-09-29) | PLANNED — next unit. Design commitments: reuse the existing push/email/manifest/service-worker owners (one transport: VAPID Web Push via pywebpush); notifications derived from the NET before/after diff of each committed transaction (never from intermediate proxy-cascade steps); outbox rows committed in the same transaction as the auction event, delivered by the runtime worker afterwards; reminders keyed to (auction, deadline revision); quiet hours 21:00-08:00 America/New_York with 08:00 re-evaluation; mocks on a fake transport unless a human tester opts in to labelled [MOCK] pushes; device tests on a real iPhone (Home Screen) and Android Chrome reported as simulated / service-accepted / device-observed / user-confirmed. To be included in the future Prompt 2 audit. |

Known engine note for AUC-002: the room's current `outbid` activity event is emitted per resolution
step inside a proxy cascade. It is private to the displaced seat and never exposes a maximum, but a
seat can in principle be displaced and restored within one committed transaction. AUC-002 replaces
it with a net per-transaction diff (the same one that drives notifications).

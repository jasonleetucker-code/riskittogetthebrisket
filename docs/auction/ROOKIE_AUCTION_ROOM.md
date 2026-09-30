# Rookie Auction Room — feature record

**Status:** **MOCK READY — deployed 2026-09-29** at https://chaseupside.com/auction (#1523 `db03f2a`, #1524 `2021c43`, #1526 `32a978f`, #1528 `00d60e0`). Official launch: **OFF**. Next state (HUMAN REHEARSAL PASSED) needs the owner's rehearsal — see `LAUNCH_CHECKLIST.md`.
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
`Origin`. Every room-changing mutation requires an `Idempotency-Key` and replays its first answer for a retry:
room commands (command log + receipts), and room creation, invites, mock clock, clone, reset links and member
removal (`route_receipts`). Sign-in, notification-preference and device routes are idempotent by construction.
The client attaches a key to every POST. Login is rate-limited by the existing throttle. The site-owner bridge
account has no password and can never be given one (`/auth/password` → 409 `site_account`). A sign-in that
replaces another account's cookie ends that account's session and silences its push devices on that browser.
Removing a person tells them in their inbox and announces "seat changed hands" to the room (no reason, audited
separately). CSV exports neutralise spreadsheet formulas in names.

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

Backups (measured in the Phase 2 recovery audit, `tests/auction/test_independent_recovery_audit.py`):

| Failure | Recovery point (RPO) | Recovery time (RTO) |
|---|---|---|
| Process crash / restart / deploy | **0**: every acknowledged action is committed before the reply (crash-injected at 9 points) | restart; the room pauses itself only if the service was really unreachable > 5 min |
| Database corruption on a healthy disk | last **hourly verified** copy (`dynasty-auction-backup.timer`, :17 each hour): ≤ ~72 min | restore + verify ≈ seconds (0.07 s for 2 rooms / 278 KB) |
| **Host or disk loss** | the last **off-host** copy. Hourly copies live on the same disk. The nightly state backup mirrors off-box **only if** `OFFBOX_RSYNC_DEST` is configured on the box (`deploy/backup/riskit-state-backup.sh`); otherwise **there is no off-host copy at all** | rebuild host + restore |

Archives are written as `.partial`, fsynced, then renamed, so a killed run never leaves a truncated file under
a verified name. Every archive is restored into a scratch store and every room replayed before it is kept. The
host-loss row is an **owner decision** before LIVE-READY (`LAUNCH_CHECKLIST.md` §B).

**Engine revisions.** Every new room is stamped `engine_rev` (now 2). A room keeps the behaviour it was played
under, so the hourly verifier's replay of an older room still reproduces its stored state exactly. Rev 2
changed only two things: lossless tie-priority history, and deferring pause/quiet-hour budget re-resolution.

**Restore procedure** (never two writers): stop `dynasty.service`, move `data/auction/auction.sqlite*` aside,
`gunzip -c data/auction/backups/auction-<stamp>.sqlite.gz > data/auction/auction.sqlite`, start the service. The
restored rooms come up paused as of their last heartbeat if the gap exceeds 5 min. Open browser tabs adopt the
restored state automatically (`storeEpoch` in `/view`), even though restored revisions are lower.

## 5. Live delivery

Revision long-poll (`GET /rooms/{id}/view?after=<rev>&wait=25`). Chosen over SSE/WebSockets because
production nginx buffers `/api/` and has a 120 s read timeout: a 25 s long-poll needs no proxy change,
every response is a complete authorised snapshot (no gaps, no replay ordering bugs), and the client
drops any response older than the revision it holds **within the same `storeEpoch`** (a new epoch — restart or
restore — is adopted even at a lower revision). Commands never wait for valuation, scrapers or Perfect Draft.

**Measured** (12 managers, ~30 tabs, ~23 commands/s, 120 s, local, `scripts/auction_load_rehearsal.py`): bid
p95 ≈ 0.61 s, accepted state visible to all other managers p95 ≈ 1.1–1.2 s, reconnect p95 ≈ 0.55–0.8 s, zero
5xx/overspend/duplicate winners/lost acknowledged actions. Production adds nginx and a slower VPS; a real slow
auction runs far below this burst rate.

## 6. Mocks

Same engine, same authorization, same ledger, same settlement. Room type is immutable and
server-owned. Mock-only: seeded bots (public information + own seeded preferences, same command
path), virtual clock jumps, clone-to-new-run. A played mock is never promoted.

## 7. Milestones

- **A — rules engine:** DONE.
- **B — first playable persistent mock:** DONE (#1523).
- **AUC-002 — notifications:** DONE in code (#1524); real-phone delivery awaits the owner's devices.
- **C — multi-user + Perfect Draft:** DONE (#1526): invitations/seat permissions/12 users, private Perfect
  Draft advice on the same spendable ledger (§11), auction-dollar trades (§11), mobile layout checked at 375px.
- **D — notifications & recovery:** DONE in code (readiness PR): reset links, seat replacement, hourly
  verified backups, outage pause, audited commissioner corrections (budget adjust, trade verification,
  member removal).
- **E — rehearsal & release readiness:** tooling DONE (preflight, rule-confirmation screen, points-for
  preview, duration simulator, launch checklist `docs/auction/LAUNCH_CHECKLIST.md`); the human rehearsals
  and owner decisions in that checklist remain.

## 8. Unresolved (owner decisions — none block mocks)

Official values for every `PROPOSED_RULE_KEYS` entry; the 2027 points-for nomination order (owner
supplies it; 2026 partial PF is not assumed final); the official 2027 rookie pool; acceptance of the
disaster-recovery window; whether open trade offers reserve money (milestone C).

## 9. Decision register (living — owner ideas during rehearsal land here)

Every new owner idea gets the next AUC id, the owner's exact wording, one classification, and the regression or
rehearsal case that proves it. Classes: **RULE CLARIFICATION** · **MOCK UX** · **LIVE-REQUIRED** (the real
2027 draft cannot operate correctly or safely without it) · **NOT REQUIRED FOR LAUNCH** · **FUTURE IDEA**. Only
LIVE-REQUIRED items join the launch denominator. The test for that class is "does the real 2027 draft need this
to operate correctly or safely?"

| Id | Owner instruction (date) | Class | State | Proof |
|---|---|---|---|---|
| AUC-001 | "Leading bids reserve money" (2026-09-29) | LIVE-REQUIRED | IMPLEMENTED + tested (§2 Money); Perfect Draft reads the same `spendable` (§11) | `test_leading_bid_reservation.py`, `test_engine_fuzz.py`, independent audit (Phase 2) |
| AUC-002 | Draft notifications: native Web Push, no SMS bill (2026-09-29) | LIVE-REQUIRED | IMPLEMENTED (§10); device delivery NOT yet observed | `test_notifications.py`; real-device evidence per `LAUNCH_CHECKLIST.md` §A |

The engine's `outbid` / `leading_again` events are now NET per committed transaction (AUC-002), pinned
by a fuzz property over every command in 40 random rooms (sabotage-verified).

## 10. Notifications (AUC-002)

**One transport per channel, all reused.** Web Push via `src/api/push_delivery.py`
(`send_push_detailed`: same pywebpush + VAPID keys as the site, plus HTTP status, `Retry-After` and a
per-message TTL), the site's `frontend/public/sw.js` + manifest, and the site's SMTP sender for an
optional, verified, explicitly-consented email backup. No SMS, no OneSignal/FCM SDK, no extra phone app,
no paid service.

| Piece | Owner |
|---|---|
| Event → notification mapping, prefs, devices, inbox/outbox, reminders, dispatcher | `src/auction/notify.py` |
| Recording INSIDE the auction transaction (SAVEPOINT; a fault cannot reject a bid) | `Store.execute` → `notify.record_transition` |
| Delivery worker (every ~2 s) + reminder scan (every ~14 s), never inside a bid | `src/auction/runtime.py` |
| HTTP: `/api/auction/notify/*`, `/rooms/{id}/watch` | `src/auction/api.py` |
| Setup page `/auction/notifications`, room inbox panel, watch toggles | `frontend/app/auction/**`, `frontend/lib/auction-notify.js` |

**Types (the owner's 14, all implemented):** your nomination turn (re-announced on resume if it began while
paused) · turn about to pass · genuinely outbid · leading again · a standing maximum newly taking the lead after
money freed (`proxy_leading`, says the money is now reserved) · player won · $0 win · 1 active hour left · deadline
extended by a late bid (bidders on that lot other than the bidder) · trade offer · dollar trade completed ·
commissioner pause · resume/recovery · draft completed. A notification that fails to dispatch is retried on its
own and never blocks anyone else's.

**Truth rules.** Alerts come from the net committed transition (A $50 vs B $39 → A at $40 sends nothing to
A). "Leading again" is sent when a SEPARATE event restores a former leader (a rival's action, or a capped
proxy reactivating after money frees) and not for the seat's own retake. Text uses public facts only; no
maximum or strategy ever appears; generic lock-screen previews are optional. Every message is timestamped,
and each is re-checked against the current room right before sending (still outbid? still your turn? same
deadline? seat still yours?) — stale ones are recorded `stale`, not sent.

**Time.** "1 active hour left" is computed on the auction clock and states the truthful closing time
("closes Wed 8:30 AM ET (bidding pauses 9 PM–8 AM ET)"). Reminders are keyed by (lot, deadline), so an
extension/settlement/pause makes the old one unmatchable; at most two last-hour reminders per lot per
person. Reminders are only generated while the room is active. Ordinary alerts recorded during the pause are
held to 08:00 ET and re-checked then; an obsolete "your turn"/"ending soon" is dropped.

**Delivery.** Outbox rows per (logical event, channel, device); unique keys give logical and per-device
dedup; the phone collapses duplicates by tag. Bounded retry with exponential backoff, provider
`Retry-After` honoured, 404/410 disables the subscription, short TTL per type, stuck sends reclaimed after
2 min (at-least-once), every state observable (`/notify/state` → "Recent deliveries").

**Identity/privacy.** Subscriptions are bound to the signed-in auction account AND the session that
registered them; sign-out, password change and expiry silence the device; the same phone switching accounts
moves the subscription. Endpoints must be https on a known push service (FCM, Mozilla, Apple, Windows) —
no arbitrary URL, no SSRF. Taps open only same-origin paths and never act. Email is opt-in, verified, and
rate-capped (`RISKIT_AUCTION_EMAIL_DAILY_CAP`, with a recovery reserve). No SMS fallback.

**Mocks.** Inbox rows are always recorded (labelled `[MOCK]`); external pushes are suppressed unless that
person turns on "[MOCK] pushes", and then capped at 30/hour. Bots have no accounts, so they never notify.

**Evidence classes (honest):**

| Class | Status |
|---|---|
| Simulated (fake transport, real store/engine) | 29 tests in `tests/auction/test_notifications.py` + SW/platform tests |
| Browser, desktop pane | Durable inbox, net outbid, [MOCK] labels, blocked-permission state and recovery copy observed on a local harness |
| Service-accepted | NOT yet — requires production VAPID keys + a real subscription |
| Device-observed / user-confirmed | NOT yet — requires the owner's iPhone (Home Screen app) and an Android Chrome phone. The setup page records a "Yes, I saw it" confirmation per test. |

Required real-device rehearsal (owner): iPhone Home Screen + Android Chrome; locked screen/background;
denied permission; restart/retry; duplicate delivery; expired subscription; overnight hold; deadline
extension; then nomination turn → push → tap → authenticated room, outbid, leading-again and a $0 win.

## 11. Perfect Draft advice and trades (milestone C)

**Advice** reuses `lib/perfect-draft.js::optimizeDraft` and the canonical roster-context builder
(`src/api/draft_optimizer_api.get_roster_context`) through `GET /api/auction/rooms/{id}/advice-context`,
which serves the caller's OWN seat only and applies the same league gate as `/api/draft/roster-context`.
`lib/auction-advice.js` maps the room: budget = the server's `spendable` (AUC-001); lots led or won are held
(money and roster room, via `applyDraftProgress`); open lots ≥ price + $1; un-nominated rookies priced by a
labelled value-share estimate; unvalued rookies left out. It runs in the manager's browser, is lazy-loaded,
keeps its strategy on the device, and never bids. The inherited $1 floors in the canonical owner
(`priceBand`, `contestedPrice`, the /draft panel's price) were removed — $0 is a real price.

**Trades** (engine-owned): versioned offers; open offers do NOT reserve money; settlement is atomic and
re-checks spendable money and lot ownership; won players move with dollars (`winner` history kept, `owner`
moves); external assets are a note that requires audited commissioner verification; no acceptance during a
pause; received money reactivates capped proxies.

## 12. Readiness tooling (milestones D/E)

- **Reset links** (`recovery.issue_reset` / `POST /auth/reset`): single-use, 24 h, hashed, audited; the member's
  inbox records the issue; use revokes every session (silencing their devices). A commissioner-issued link
  could be used by the commissioner — inherent, so it is audited and announced, not hidden.
- **Replace a person**: removes the member (audited reason); the SEAT keeps its money, bids and players; a
  fresh invite binds the new person.
- **Preflight**: seats claimed, budgets + provenance, pool approval, rule confirmations, order basis, push keys,
  last verified backup, room type.
- **Points-for preview**: reads Sleeper, states the season and whether it is final, flags ties; applying is a
  separate audited `set_order`.
- **Hourly verified backups**: `scripts/auction_backup_verify.py` via the `dynasty-auction-backup` timer —
  online copy → restore into a scratch store → replay every room → keep + record. On-host.
- **Duration** (`scripts/auction_simulate.py`, 12 seeded bots, proposed official timing): median ≈ 31.3
  calendar days (30.5–31.5, 3 rooms); ≈ 31.5 with up to 6 active hours of nomination latency. The 65-hour lot
  clock, not nomination speed, sets the length, because 12 lots run in parallel. Bots do not bid late, so real
  late-bid extensions make ~31 days a floor, not a forecast.

## 13. Rehearsal problem reports (Phase 2)

`src/auction/feedback.py` + `POST/GET /api/auction/rooms/{id}/reports` + the room's **Report a problem** panel.
A report stores the person's words plus what the server knew: room, committed revision, room clock, rules
version, pool version, the lot (if named) and the deployed commit (`git rev-parse HEAD`, or `RISKIT_CODE_SHA`).
Reporter sees their own; the commissioner sees all. It is not a room command, so the revision does not move.
It is idempotent and same-origin. `/meta` and preflight also publish `codeSha`. Rooms are never deleted, so a
failed run stays replayable. Owner-facing steps: `REHEARSAL_GUIDE.md`.

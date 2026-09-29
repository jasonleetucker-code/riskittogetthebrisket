# Rookie Auction Room — official launch checklist

**Official launch is OFF.** The API refuses `roomType: "official"` (`official_launch_gated`) until the owner
explicitly approves launch. This list is what that approval should rest on. Each line names who can close it.
States: IMPLEMENTED → MOCK READY → HUMAN REHEARSAL PASSED → LIVE-READY → OWNER LAUNCH APPROVED.

## A. Evidence the owner must produce (cannot be done by an agent)

- [ ] **Real iPhone Home Screen notification test** — Add to Home Screen, sign in inside the app, turn on,
      send a test, tap "Yes, I saw it". Then lock the phone and receive: your turn, outbid, leading again, a $0
      win. Record device + iOS version. *(owner)*
- [ ] **Real Android Chrome notification test** — same flow, including background/locked. *(owner or a league-mate)*
- [ ] **Denied permission + recovery** on each phone. *(owner)*
- [ ] **Multi-day real-clock rehearsal** — a `rehearsal` or `official`-timing mock with at least 3 humans across
      at least one overnight pause (verify nothing binding happens 9 PM–8 AM ET, held alerts arrive after 8 AM and
      obsolete ones do not). *(owner + league-mates)*
- [ ] **User-guided rehearsal** — invite league-mates to a mock; everyone claims a seat, bids, nominates, trades. *(owner)*
      Step-by-step scripts for all three rehearsal kinds: `REHEARSAL_GUIDE.md`. Every problem goes through the room's
      **Report a problem** panel (pinned to revision, rules, pool and deployed commit).

## B. Owner decisions (recorded, not invented)

- [ ] Confirm every proposed rule on the room's rule screen (`src/auction/rules.py::PROPOSED_RULE_KEYS`):
      65 active-hour lot clock, 1 active-hour extension, 13 active-hour nomination timeout + audited pass,
      earliest-accepted tie rule, withdrawal policy, outage policy (pause + fair window), money-spent and
      rights-exhausted endings, six rounds = six nomination turns, commissioner corrections, and whether open
      trade offers reserve money (`open_trade_offers`; current rule: they do not, settlement re-checks).
- [ ] Supply/confirm the official **points-for nomination order** (the room's preview reads Sleeper and says
      whether the season is final; ties are flagged for you to decide).
- [ ] Approve the **official 2027 rookie pool** (no official class exists in the data yet; mocks use a labelled
      fixture). The room refuses to start an official room without it.
- [ ] Accept the **disaster-recovery window** or authorise an off-host copy: hourly verified backups bound a
      process/database fault to ~1 hour, but they are on the same host; losing the disk loses everything since
      the last off-host copy.
- [ ] Approve launch (flip the official-room gate in a reviewed PR).

## C. Engineering (agent-closable; status in `ROOKIE_AUCTION_ROOM.md`)

- [x] Engine, proxy rules, AUC-001 reservation, calendar, completion — tested incl. adversarial fuzz.
- [x] Persistent store, idempotency, replay verification, fail-closed open, restore drill.
- [x] Scoped identity, invites, reset links, seat replacement, server-side authorization.
- [x] Notifications (AUC-002): inbox, outbox, Web Push via existing VAPID owner, email opt-in.
- [x] Perfect Draft advice (same spendable ledger), auction-dollar trades.
- [x] Hourly verified backup timer (`dynasty-auction-backup`), preflight, duration simulator.
- [x] Independent adversarial review (2026-09-29): 7 confirmed defects + hardening items resolved, each with a
      regression test (`tests/auction/test_review_regressions.py`, notification/SW tests). Money rules held under the
      reviewer's own 600-run fuzz. A second review after the owner's rehearsal is recommended.
- [x] Deployed and verified on production (mock rooms) — `https://chaseupside.com/auction` (2026-09-29: page and
      API live, room data requires an auction sign-in, cross-origin writes refused, SW v9 never caches auction data).
- [ ] **Production VAPID keys — NOT configured (measured 2026-09-29: `/api/push/public-key` → 503
      `push_not_configured`).** Without them no phone push is possible (the in-app inbox still works). Owner action:
      generate a key pair with the one-liner in `.env.example` (Web Push section), add `VAPID_PUBLIC_KEY`,
      `VAPID_PRIVATE_KEY` and `VAPID_CONTACT=mailto:<a real address>` to `/home/dynasty/trade-calculator/.env`
      on the box, then restart the backend service. Free and self-signed — no account, no subscription.
- [ ] Hourly verified-backup timer running on the box (`systemctl status <service>-auction-backup.timer`;
      preflight shows the last verified backup once it has run).

## D. Launch-day runbook (once A–C are done)

1. Create the official room from the reviewed configuration (never promote a played mock).
2. Preflight must be all `ok`; confirm budgets total and provenance (2027 draft capital, overrides audited).
3. Issue handle-locked invites to the 12 managers; confirm every seat is claimed.
4. Confirm the nomination order and rules on the room's screens; start inside the active window.
5. Watch: `journalctl -u <service>-auction-backup`, `/api/auction/rooms/{id}/preflight`, the room's sync badge.
6. Outage: the room pauses itself on restart after a >5 min gap; resume with an announced fair window.

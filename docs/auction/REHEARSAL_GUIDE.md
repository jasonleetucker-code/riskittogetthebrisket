# Rookie Auction Room — rehearsal guide

**For:** the owner (commissioner) and league-mates rehearsing at https://chaseupside.com/auction.
**State ladder:** MOCK READY → **HUMAN REHEARSAL PASSED** (this guide produces the evidence) → LIVE-READY →
OWNER LAUNCH APPROVED. Official rooms stay switched off throughout. Every room below is a MOCK: nothing touches
Sleeper, real rosters, real budgets or official price history.

**When something looks wrong:** press **Report a problem** in the room (right column, bottom). Say what happened
and what you expected, and pick the lot if it was about one. The server records the exact room revision, room
clock, rules version, pool version and deployed commit with your words, so the run can be replayed. You don't
need a screenshot. Failed rooms are never reset or deleted. Keep playing, or clone the room to start over.

## 0. Before the first mock (one time)

1. Sign in to Chase Upside with your normal site login, open `/auction`, press **Continue as site owner**.
2. iPhone push (after the VAPID keys are installed on the server): in Safari open `chaseupside.com/auction`,
   Share → **Add to Home Screen**, then open Chase Upside **from the Home Screen icon** (push only works there),
   sign in, go to **Phone alerts**, tap **Turn on notifications** → **Allow**, then **Send a test**.
   Lock the phone. When it arrives, tap **Yes, I saw it** on the setup page. Don't go into iOS Settings first:
   the app has to ask for permission itself before Chase Upside appears there.

## 1. Solo mock: you + 11 bots (10–15 minutes, repeat freely)

Create room: Timing **Fast**, Seats **The 12 league teams**, Budgets **Current draft capital**, tick **Fill every
other seat with a bot**. Start it.

Try each of these and note anything that surprises you:

1. Nominate a rookie. It opens at **$0** with you leading at $0.
2. Set your max to $0 on a lot a bot opened. Equal $0 maxima: the earlier bid keeps the lead.
3. Set a max of $50 on a lot where the price is $0 and nobody else bids. The price stays $0.
4. **AUC-001:** note **Spendable now** in **Your money**. Take the lead somewhere at $X. Spendable must drop by
   exactly $X, with the $X shown under "Reserved — lots you lead". When a bot outbids you, it must come back.
   When a lot you lead closes, the $X must move into the balance once (balance falls by $X, reserved falls by
   $X), never twice.
5. Try to bid more than your available money on a second lot. The server may store the max, but it must never
   make you lead at a price you can't pay.
6. Open the **Perfect Draft** panel. Its budget must equal **Spendable now**, not your balance.
7. Commissioner panel: advance the mock clock to close lots. Pause, then resume.
8. Check **Your alerts** (in-app inbox). Winning a player, including at $0, must show there.
9. **Report a problem** once, even a trivial one, so the loop is exercised.

## 2. Small human mock: you + 1–3 league-mates + bots (30–60 minutes)

Create room: Timing **Fast** (or **Rehearsal** to include the real 9 PM–8 AM pause), bots on. Before starting,
use **Create invitation link** once per person, picking their seat and locking it to their handle. Send each link
privately. It works once and expires in 7 days.

Ask everyone to:

1. Open the link on their **phone**, create a Chase Upside auction password (never their Sleeper password),
   claim their seat, and turn on phone alerts if they're willing.
2. Bid against each other on the same lot at the same time. Exactly one person should lead, at the correct
   second-price amount (A max $50 vs B max $39 → A at **$40**). A must **not** get an "outbid" then "leading
   again" pair.
3. Propose an auction-dollar trade to someone. Accept it. Then try accepting one after the money is tied up in a
   lead (it must fail cleanly, not overspend).
4. Put the phone to sleep for a few minutes, wake it, and check that the room catches up by itself without going
   back to an older state.
5. Report anything confusing with **Report a problem**.

## 3. Real-clock multi-day rehearsal (several days, at least 3 humans)

Create room: Timing **Proposed official (65h, real quiet hours)**, league seats, draft-capital budgets, bots on
for the seats nobody claims. Invite as in §2. Run it for at least one overnight pause, preferably three or more
days. Things to watch for and report:

- Nothing binding happens between 9 PM and 8 AM ET. Bids placed then are refused, and clocks are frozen.
- A lot with one active hour left at 8:30 PM closes at **8:30 AM** the next day, unless someone bids in the last
  active hour and extends it.
- Morning alerts: only ones still true are delivered. No stale "ending soon" for a lot that already closed or
  was extended.
- The room recovers by itself after a site deploy (deploys happen several times a day).

## What makes the rehearsal count

Record in the rehearsal log below. HUMAN REHEARSAL PASSED needs: §2 done with at least two humans on phones, §3
done with at least three humans across at least one overnight pause, every report triaged (fixed with a
regression test, or explicitly accepted by the owner), and iPhone push **device-observed**.

## Rehearsal log

| Date | Room | Type | People / devices | Duration | Reports | Outcome |
|---|---|---|---|---|---|---|
| | | | | | | |

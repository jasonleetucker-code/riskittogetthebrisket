# Real-device checklist — iPhone — 2026-11-19

Owner-executable. Intake STAB-9. Automation cannot prove these; this list is
what is left after `tests/e2e/specs/mobile-device-flows.spec.js`.

## Read this first: emulation is not a physical device

The browser suite runs two "phone" projects. Neither is an iPhone.

| Project | What it really is | What it cannot show |
|---|---|---|
| `mobile-chromium` | Chromium, 390 x 844 viewport, touch events on | any iOS behaviour at all |
| `mobile-390` / `mobile-430` | Playwright's WebKit with the iPhone 13 / 14 Pro Max device profile | real touch hardware, iOS Safari's toolbars and safe areas, VoiceOver, the home-screen PWA container, iOS service-worker and background rules, iOS keyboard, iOS text size |

A green E2E run therefore means: "the app's own logic and layout behave on a
phone-sized touch browser". It does **not** mean "it works on an iPhone". Every
item below needs a person holding the phone. Record what you saw; do not infer.

**Setup for all items:** a physical iPhone, iOS 17 or later (write the exact
version, Settings > General > About), signed in to chaseupside.com in Safari.
For items that say "home-screen app", first Share > Add to Home Screen, then
open it from the icon. Note Safari or home-screen app for every result.

**Report format, for every item:** item number, PASS / FAIL / CANNOT TEST, iPhone
model, iOS version, Safari or home-screen app, and one sentence or screenshot of
what happened. A FAIL needs the steps you took.

---

## 1. Tap to pick in the waiver add/drop pickers

What automation covers: a tap and a keyboard pick on an emulated touch screen,
and that a swipe that *starts* on an option does not pick it. What it cannot:
how a real finger on a real glass screen feels, scroll momentum, mis-taps.

Steps:
1. Open **Waivers** (`/waivers`). If a team is not selected, pick yours from the
   team control at the top.
2. Scroll to **Manual add/drop calculator**.
3. Tap the **Drop** search box. The list of candidates opens.
4. Tap one player once, firmly but normally.
5. Tap the small clear (x) control next to the pick. Tap the box again.
6. With the list open, put a finger on a player row and **scroll the page and the
   list by dragging** (start the drag on a row, several times, slowly and fast).
7. Repeat steps 3-6 on the **Add** box.

Expected:
- Step 4: exactly that player is chosen, the list closes, no flicker, no second
  player chosen, no tap "falls through" to something underneath.
- Step 5: choice clears; the list reopens.
- Step 6: dragging scrolls. **No player is chosen by a drag.** This is the defect
  #2223 fixed; it is the main thing to try to break.

Report: any drag that chose a player, any tap that needed two tries, any tap that
chose a different row than the one under the finger.

## 2. VoiceOver on the same pickers

What automation covers: that the combobox, listbox and options expose names,
roles and selected state in the browser accessibility tree. That is a *proxy*;
it is not VoiceOver.

Steps:
1. Settings > Accessibility > VoiceOver on (or triple-click the side button if
   you have set that shortcut).
2. Open `/waivers`, select your team, find **Manual add/drop calculator**.
3. Swipe right until VoiceOver lands on the **Drop** search field. Note exactly
   what it says.
4. Double-tap to focus, type two letters. Swipe right through the results.
5. Double-tap a result to pick it. Note what VoiceOver says, and where focus goes.
6. Repeat on the **Add** field.

Expected:
- Step 3: it announces a search field for drop candidates (an edit/combobox), not
  "text field" with no context.
- Step 4: each result is read as one item containing the player's name (and
  position/team/value text), and says whether it is selected. Results are
  reachable by swiping; none is skipped.
- Step 5: the pick is announced; focus lands on the clear control for that side
  (not the top of the page).

Report: the exact words VoiceOver spoke at steps 3-5, and anything it skipped,
read twice, or read as "button" with no name.

## 3. Installed iPhone app updates after a new deploy

What automation covers: that when a new worker takes control the page reloads
once, caches from older versions are deleted, and private API responses are never
stored. What it cannot: iOS's own rule that a waiting worker may not activate
until every app window closes, background suspension, and when iOS checks for
updates. This is the item most likely to differ from the test.

Steps (needs a deploy to happen while the app is installed; do not force one):
1. Before a known deploy, open the **home-screen app**. Go to Settings and note
   the build shown on the status or about screen, or open
   `https://chaseupside.com/api/status` in Safari and note `build.commit`.
2. Use the app normally for a minute, then switch away from it (Home).
3. After the deploy has finished (`/api/status` shows a new `build.commit`),
   wait 5 minutes without opening the app.
4. Open the app from its icon. Note what you see for the first 10 seconds.
5. If it still looks old, pull-to-refresh once; note whether that fixed it.
6. Fully close the app (swipe up, flick it away), reopen. Note the result.

Expected: on step 4 or 5 at the latest the app is on the new build (check against
`/api/status`), with no blank screen, no endless reload, and no screen that loads
half and fails ("missing component"). Data you see is fresh, not stale from last
night.

Report: which step the new version first appeared, and any blank screen, reload
loop or "failed to load" text. Say if you had to close the app fully.

## 4. The 4-team War Room summary bar at 390 px

What automation covers: on a 390 px emulated phone, with four teams on `/trade`,
the summary bar stays inside the screen width and does not overlap the
screenshot button or the bottom tab bar, including with a long verdict and a
25 % larger font. It cannot see iOS's real toolbar, home indicator or text size.

Steps:
1. Open **Trade** (`/trade`) in Safari, portrait, 390-wide iPhone (iPhone 12-15).
2. Tap **Add Team** twice so there are four sides (A to D).
3. Add one player to each side.
4. Look at the bar pinned at the bottom: the four team figures and the line under
   them. Scroll the page up and down.
5. Settings > Display & Brightness > Text Size: move the slider about two steps to
   larger; return to Safari and look again.
6. Repeat step 4 as a home-screen app.

Expected: the whole bar is visible above the tab bar; nothing is cut off at either
edge; the round screenshot button is above the bar and does not sit on top of any
of its text or buttons, at normal and larger text; the Safari toolbar or home
indicator does not hide any of the bar.

Report: a screenshot at normal and at larger text. Anything covered, clipped or
unreadable.

## 5. Live auction room (NOT automated)

The offline test stack cannot create a room (it needs the site-owner account), so
the room screen has **no** automated coverage; only the entry screens (`/auction`,
`/auction/join`, an unknown room) are checked for render and 44 px controls.

Steps (needs a real or mock room; create a mock rookie auction as the site owner
if there is none):
1. Open the room link on the iPhone, sign in as a league member.
2. Wait for the live lot. Watch the clock, the current bid and your budget.
3. Place a bid with the on-screen bid controls. Then try the quick-bid buttons.
4. Lock the phone for 30 seconds, unlock, return to Safari.
5. Turn on Airplane Mode for 10 seconds, turn it off.
6. If notifications are enabled, background the app and wait for a notification;
   tap it.

Expected: the lot, clock and bid update without reloading; every bid control is
easy to hit with a thumb and nothing is covered by the tab bar or keyboard; after
step 4 and step 5 the room reconnects and shows the true current state (not a
stale bid) within a few seconds and says it is reconnecting while it does; a
notification opens the correct room.

Report: anything hard to tap, any stale bid shown as current, time to recover in
steps 4 and 5, and what the notification opened.

## 6. Navigation, sticky controls, primary touch targets

What automation covers: the bottom tab bar, drawer, pinned trays and primary
controls on emulated 390 px layouts (existing `mobile-smoke`,
`mobile-pinned-overlap`, `mobile-target-size` specs). What it cannot: whether they
are comfortable under a real thumb with iOS's chrome around them.

Steps (Safari and home-screen app, portrait):
1. Tap each bottom tab; tap **Menu**; open and close the drawer.
2. Scroll a long page (`/rankings`) to the bottom and back; watch the pinned
   header and tab bar.
3. On `/trade`, add a player to each side; watch the pinned totals bar.
4. Try the top five buttons you use most on `/rankings`, `/trade`, `/waivers`.
5. Rotate to landscape and back on `/trade`.

Expected: every tap lands on the first try with a normal thumb; pinned bars never
hide content you need or each other; nothing jumps when Safari's toolbar collapses
or the home indicator appears; rotating does not leave a pinned bar floating or
off screen.

Report: any control you missed or had to retry, and where (screenshot).

## 7. Recovery after a failed request

What automation covers: when the board's request fails or hangs, the page shows a
named failure with **Try again**, the 25-second limit is honoured, and Try again
loads the board. What it cannot: real cellular drops, iOS suspending the page.

Steps:
1. Open `/rankings` and wait for the board.
2. Turn on Airplane Mode. Pull to refresh, or reload the page.
3. Read the message and note the button. Turn Airplane Mode off.
4. Tap **Try again** (not reload).
5. Repeat on a weak connection if you can (move to a poor-signal spot, or use
   Settings > Developer > Network Link Conditioner if you have it set up).

Expected: a clear failure message ("Could not reach the server" or "Request timed
out") that is not a blank page, not a spinner that never ends, and not old data
presented as current; **Try again** works without a reload; a hang ends within
about 25 seconds.

Report: the exact message, how long you waited, whether Try again worked.

---

## What to send back

One message: a table with items 1-7, PASS / FAIL / CANNOT TEST, device, iOS
version, and your note per item. Failures with steps and a screenshot. If items
1 and 3 pass on a real device, STAB-9's physical-device items for the picker and
PWA update can be closed; items 2, 5 need a person who uses VoiceOver / runs a
room, so say if you could not test them rather than marking them passed.

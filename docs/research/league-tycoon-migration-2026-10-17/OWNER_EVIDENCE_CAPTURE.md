# Owner evidence capture: the smallest set of steps that unblocks verified access

Research is blocked on one thing only: nobody has observed League Tycoon while signed in. This page lists exactly
what the league owner does, what each step enables, and what must **never** leave the owner's computer.

## Before anything else (no computer work)

1. **Ask League Tycoon.** Send one message to support@leaguetycoon.com, or post in their Discord. Template:

   > I'm the commissioner of a dynasty league moving from Sleeper. Three questions:
   > (1) Do you support IDP (DL/LB/DB starters, IDP scoring like tackles/sacks/TFL/PD) and best-ball lineups?
   > (2) Is there any export, API or read access for a commissioner's own league data?
   > (3) Our league runs a non-commercial companion analytics site. May I use a script to read my own
   > league's data at a low rate (a few page loads every couple of hours), read-only?

   - **Enables:** Deliverable 1 conditions 1 and 2 are settled for free.
   - A written "yes" to (3) removes the Terms-of-Use risk entirely (README §1.5).
2. **Answer the owner decisions** in README §11. OD-1 through OD-4 are needed before Batch 1.

## The capture (about 20 minutes, on the owner's own computer)

**What you need:** desktop Chrome or Edge, signed in to League Tycoon with your usual Google/Apple account. Nothing
here asks for your password, and you should never send one.

1. Open `https://app.leaguetycoon.com`, sign in normally, and open your league.
   - **Enables:** proves which league id is yours. Look at the address bar.
2. Press `F12`, then open the **Network** tab.
   - Tick **Preserve log**.
   - Filter to **Fetch/XHR**. If almost nothing shows, also check **WS** (WebSocket) and **All**: a Firebase app
     may stream data instead.
3. Visit these screens in order, waiting for each to finish loading:
   1. League home
   2. Standings
   3. Every team's roster (open at least 3 teams other than yours)
   4. One player card, including contract details if you have them
   5. League settings: scoring
   6. League settings: roster / lineup slots
   7. League settings: financial / cap (contract leagues)
   8. Salary-cap / team finances page
   9. Transactions / activity
   10. Trade history (and a trade auction, if one is visible)
   11. Draft picks / future picks
   12. Past drafts (rookie and any auction)
   13. This week's matchup, and one past week
   14. A past season (season dropdown) and the Hall of Fame
   15. One player's weekly scores
   16. Auctions / free agency
   17. Free-agent list
   18. Commissioner tools: **view only, change nothing**
4. In the Network panel, right-click → **Save all as HAR with content**. Save it locally as
   `lt_capture_<date>.har`.
5. **Do not share the HAR.** It contains your session token. Instead:
   - **Until the Batch-1 sanitizer exists:** for each screen, click the largest request, open **Response**,
     copy it into a text file, and **delete** any line containing `token`, `auth`, `session`, `cookie`,
     `password`, or an email address.
   - **After Batch 1:** run `python scripts/league_tycoon/sanitize_capture.py lt_capture_<date>.har`. It produces a
     redacted field-shape report and refuses to run if it finds a different league id. Share **only that report**.
6. Note what the address bar showed for the league URL, and send that too.
   - **Enables:** the league id is proven against the candidate `1416568994525167616`.

## What the capture answers

| Screen(s) | Unblocks |
|---|---|
| 1, URL | league id, season id format |
| 2, 3 | team / manager ids, roster shape, IDP presence, practice squad / IR |
| 4 | player id scheme → crosswalk (SportsDataIO or not); contract fields |
| 5, 6 | scoring vocabulary, IDP keys, best ball, slot names |
| 7, 8 | cap ledger fields |
| 9, 10 | transaction types, ids, timestamps, legs, cap-dollar trades, trade-auction offers |
| 11, 12 | pick origin / holder, comp picks, draft formats, auction prices |
| 13–15 | matchups, lineups, stat lines, schedule visibility of future weeks, rebuilt history |
| 16, 17 | auction / FA data |
| 18 | which data is commissioner-only (we read none of it automatically) |
| Network shape overall | whether data arrives as REST/JSON (replayable) or a Firestore-style stream (capture-only); auth header type; caching; pagination |

## Never

Never send or commit any of these:

- a password
- an unredacted HAR
- a cookie
- an `Authorization` header
- an `idToken` / `refreshToken`
- other managers' email addresses

Never capture another league, and never click anything that changes league state during the capture.

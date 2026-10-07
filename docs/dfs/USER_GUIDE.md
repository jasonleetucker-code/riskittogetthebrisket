# DFS Workspace — user guide (current slice)

Open **DFS → DFS Workspace** (`/dfs`). Sign-in required.

1. **Pick sport and platform.** The badge says what is possible: *Research only — rules
   unverified* (you can build; the rule set has not been checked against the official page) or
   *Not available yet* (no rules encoded — nothing can be built). Today NFL, NBA and NHL Classic on
   DraftKings and FanDuel, and DraftKings NFL Showdown, can build (all research-only). In Showdown
   the captain's 1.5× is shown next to the number, and the same player can never be captain and
   flex. DraftKings MMA builds too (research-only; add an 'if A then not B' rule if you do not want both fighters from one bout). FanDuel MMA and other single-game files are recognised but cannot be built yet.
2. **Pick a slate — nothing to download.** For NFL on DraftKings or FanDuel, *Slate* already lists
   this week's slates (Main, Early, Afternoon, Primetime, Full week), each with its lock time, games,
   players, how many are projected, and a freshness badge (*Current*, *Aging*, *Stale*, *Degraded*,
   *Source error*). Main opens by default. Salaries, positions, games, kickoffs, injury status and
   projections are filled in automatically and refresh on their own — more often as lock
   approaches. The game set of each slate is derived from the NFL schedule (the platforms' own slate
   lists are not available to us), and the badge says when a source is missing or failed. Players
   ruled Out / IR are left unprojected so no lineup can include them; nobody is ever scored 0 for
   missing data. **One limit:** automatic slates use our own player IDs, so they build, simulate and
   late-swap normally but cannot produce a DraftKings / FanDuel upload file.
   **NBA and NHL** work the same way with one difference: each platform's slate is the dated
   slate Daily Fantasy Fuel lists (usually that night's main slate), timed from the league
   schedule — other same-day slates are not available to us. NHL slates also carry each skater's
   projected line and power-play unit, and say how many goalies are not yet confirmed starters
   (a goalie who does not start scores nothing — confirm yours before lock). When no slate is
   listed (an off day, or before the regular season starts) the panel says so and checks again
   hourly.
   **Advanced · Data overrides / manual import** (optional) is where the old path lives: the
   platform's salary / player-list CSV (which IS upload-ready — the page tells you what the file is,
   e.g. *Detected: FanDuel · NFL · Classic*, and offers to switch if it does not match), your own
   projection CSV (`ID` or `Name` + `Team` + `Projection`; rows that match two players, nobody, or
   disagree are listed and not applied), ownership, and the licensed-feed loader (not connected).
   MMA still needs the platform file here for now. Optionally tick *use the platform
   season average* for players you have no projection for — it is labelled "avg" and is
   not a forecast. Players with no projection are never counted as 0; they are left out.
3. **Describe the contest (optional today).** In *Contest*, enter the fee, capacity, current
   entries, your entry limit and existing entries, whether prizes are guaranteed, the tie rule,
   and paste the payout table (`1 $1,000`, `2-5 $100`, …). *Check contest* shows paid places,
   first-place share, min cash, rake vs overlay, what two entries tied for first would each get,
   and — only if you type a spend limit — the most entries you could add. Blank means unknown,
   never zero. Saving again creates a new version. The strategy presets listed there are not
   available yet: each names the models it still needs.
4. **Set rules.** Lock / Exclude per player; lineups, minimum unique players, max exposure % (the
   count shown is rounded down), minimum salary, max players per team, and an optional QB stack
   with bring-back.
5. **Build.** *Optimal Lineup* builds one lineup; *Build Portfolio* builds the number you set.
   Both maximize **projected points** — not contest EV. *optimal* means no higher projected
   total exists under your rules. If your rules conflict, you get the conflicting set; nothing
   is relaxed.
6. **Export.** *Download upload CSV* writes platform IDs in slot order. The upload format has not
   been verified against an official template yet — check it before uploading. Downloading
   submits nothing.

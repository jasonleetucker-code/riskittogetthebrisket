# DFS Workspace — user guide (current slice)

Open **DFS → DFS Workspace** (`/dfs`). Sign-in required.

1. **Pick sport and platform.** The badge says what is possible: *Research only — rules
   unverified* (you can build; the rule set has not been checked against the official page) or
   *Not available yet* (no rules encoded — nothing can be built). Today NFL, NBA and NHL Classic on
   DraftKings and FanDuel, and DraftKings NFL Showdown, can build (all research-only). In Showdown
   the captain's 1.5× is shown next to the number, and the same player can never be captain and
   flex. DraftKings MMA builds too (research-only; add an 'if A then not B' rule if you do not want both fighters from one bout). FanDuel MMA and other single-game files are recognised but cannot be built yet.
2. **Import the slate.** Download the platform's salary / player-list CSV for your contest and
   choose it (or paste it). The page tells you what the file is (e.g. *Detected: FanDuel · NFL ·
   Classic*) and offers to switch if it does not match your selection — it never switches on its
   own. A licensed feed (SportsDataIO) can load slates automatically once it is connected; today
   it shows *not connected* and the file path is the one that works. After import, *Data
   freshness* shows each kind of information and whether it is available. Add your projection CSV: columns `ID` (platform player ID) or
   `Name` + `Team` (+ optional `Position`), and `Projection`. Rows that match two players, match
   nobody, or disagree with each other are listed and **not** applied. Optionally tick *use the
   platform season average* for players you have no projection for — it is labelled "avg" and is
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
